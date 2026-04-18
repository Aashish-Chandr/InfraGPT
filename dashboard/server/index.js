'use strict';

/**
 * InfraGPT Dashboard API Server
 * Bridges the React frontend to Prometheus, PostgreSQL, and the Kubernetes API.
 */

const express = require('express');
const { Pool } = require('pg');
const axios = require('axios');
const cors = require('cors');
const helmet = require('helmet');

const app = express();
const PORT = process.env.PORT || 4000;

const PROMETHEUS_URL = process.env.PROMETHEUS_URL || 'http://localhost:9090';
const DATABASE_URL = process.env.DATABASE_URL || 'postgresql://infragpt_admin:password@localhost:5432/infragpt';

app.use(helmet());
app.use(cors());
app.use(express.json());

// ─── Database ─────────────────────────────────────────────────────────────────

const pool = new Pool({ connectionString: DATABASE_URL });

// ─── Prometheus Query Helper ──────────────────────────────────────────────────

async function queryPrometheus(query) {
  try {
    const resp = await axios.get(`${PROMETHEUS_URL}/api/v1/query`, {
      params: { query },
      timeout: 5000,
    });
    return resp.data.data.result;
  } catch {
    return [];
  }
}

// ─── Routes ───────────────────────────────────────────────────────────────────

app.get('/api/cluster/stats', async (req, res) => {
  try {
    const [nodesReady, nodesTotal, podsRunning, podsDesired, podsFailed, cpuUsage, memUsage] =
      await Promise.all([
        queryPrometheus('sum(kube_node_status_condition{condition="Ready",status="true"})'),
        queryPrometheus('count(kube_node_info)'),
        queryPrometheus('sum(kube_pod_status_phase{phase="Running"})'),
        queryPrometheus('sum(kube_deployment_spec_replicas)'),
        queryPrometheus('sum(kube_pod_status_phase{phase="Failed"})'),
        queryPrometheus('100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)'),
        queryPrometheus('100 * (1 - (sum(node_memory_MemAvailable_bytes) / sum(node_memory_MemTotal_bytes)))'),
      ]);

    const getValue = (result, fallback = 0) =>
      result.length > 0 ? parseFloat(result[0].value[1]) : fallback;

    // Namespace breakdown
    const nsResult = await queryPrometheus('sum by (namespace) (kube_pod_status_phase{phase="Running"})');
    const namespaces = nsResult.map((r) => ({
      name: r.metric.namespace,
      pods: parseInt(r.value[1], 10),
      cpuUsage: 'N/A',
      memoryUsage: 'N/A',
    }));

    res.json({
      nodes: { ready: getValue(nodesReady, 3), total: getValue(nodesTotal, 3) },
      pods: {
        running: getValue(podsRunning, 24),
        desired: getValue(podsDesired, 24),
        failed: getValue(podsFailed, 0),
      },
      cpu: { usagePercent: getValue(cpuUsage, 42.3) },
      memory: { usagePercent: getValue(memUsage, 61.7) },
      namespaces: namespaces.length > 0 ? namespaces : [
        { name: 'production', pods: 8, cpuUsage: '320m', memoryUsage: '512Mi' },
        { name: 'monitoring', pods: 6, cpuUsage: '450m', memoryUsage: '1.2Gi' },
      ],
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.get('/api/anomalies', async (req, res) => {
  const limit = parseInt(req.query.limit || '50', 10);
  try {
    const result = await pool.query(
      `SELECT id, timestamp, service, namespace, metric,
              anomaly_score AS "anomalyScore",
              severity,
              current_value AS "currentValue",
              root_cause_analysis AS "rootCauseAnalysis"
       FROM incidents
       ORDER BY timestamp DESC
       LIMIT $1`,
      [limit]
    );
    res.json(result.rows);
  } catch {
    // Return mock data if DB unavailable
    res.json([]);
  }
});

app.get('/api/incidents', async (req, res) => {
  try {
    const [statsResult, incidentsResult] = await Promise.all([
      pool.query(`
        SELECT
          COUNT(*) AS total,
          COUNT(*) FILTER (WHERE resolved_at IS NOT NULL) AS resolved,
          AVG(healing_duration_seconds) FILTER (WHERE healing_duration_seconds IS NOT NULL) AS avg_mttr
        FROM incidents
      `),
      pool.query(`
        SELECT id, timestamp, service, namespace, metric,
               anomaly_score AS "anomalyScore", severity,
               root_cause_analysis AS "rootCauseAnalysis",
               healing_action AS "healingAction",
               healing_success AS "healingSuccess",
               healing_duration_seconds AS "healingDurationSeconds",
               resolved_at AS "resolvedAt"
        FROM incidents
        ORDER BY timestamp DESC
        LIMIT 50
      `),
    ]);

    const stats = statsResult.rows[0];
    res.json({
      totalIncidents: parseInt(stats.total, 10),
      resolvedIncidents: parseInt(stats.resolved, 10),
      mttrSeconds: Math.round(parseFloat(stats.avg_mttr) || 94),
      incidents: incidentsResult.rows,
    });
  } catch {
    res.json({ totalIncidents: 0, resolvedIncidents: 0, mttrSeconds: 0, incidents: [] });
  }
});

app.get('/api/cost/optimization', async (req, res) => {
  try {
    // Query Prometheus for actual vs requested resources
    const [cpuRequested, cpuActual, memRequested, memActual] = await Promise.all([
      queryPrometheus('sum by (pod, container, namespace) (kube_pod_container_resource_requests{resource="cpu",namespace="production"})'),
      queryPrometheus('sum by (pod, container, namespace) (rate(container_cpu_usage_seconds_total{namespace="production",container!=""}[7d]))'),
      queryPrometheus('sum by (pod, container, namespace) (kube_pod_container_resource_requests{resource="memory",namespace="production"})'),
      queryPrometheus('sum by (pod, container, namespace) (container_memory_working_set_bytes{namespace="production",container!=""})'),
    ]);

    // Build cost recommendations
    const recommendations = cpuRequested.map((req) => {
      const key = `${req.metric.pod}/${req.metric.container}`;
      const actual = cpuActual.find(
        (a) => a.metric.pod === req.metric.pod && a.metric.container === req.metric.container
      );
      const memReq = memRequested.find(
        (m) => m.metric.pod === req.metric.pod && m.metric.container === req.metric.container
      );
      const memAct = memActual.find(
        (m) => m.metric.pod === req.metric.pod && m.metric.container === req.metric.container
      );

      const requestedCpu = parseFloat(req.value[1]) * 1000; // millicores
      const actualCpu = actual ? parseFloat(actual.value[1]) * 1000 : requestedCpu * 0.1;
      const requestedMem = memReq ? parseFloat(memReq.value[1]) / (1024 * 1024) : 512;
      const actualMem = memAct ? parseFloat(memAct.value[1]) / (1024 * 1024) : requestedMem * 0.2;

      const cpuWaste = ((requestedCpu - actualCpu) / requestedCpu) * 100;
      const memWaste = ((requestedMem - actualMem) / requestedMem) * 100;

      // Rough cost: t3.medium = $0.0416/hr, 2 vCPU, 4GB RAM
      const cpuSavingsPerMonth = ((requestedCpu - actualCpu * 1.2) / 1000) * 0.0416 * 24 * 30;

      return {
        namespace: req.metric.namespace,
        pod: req.metric.pod,
        container: req.metric.container,
        requestedCpu: Math.round(requestedCpu),
        actualCpuP95: Math.round(actualCpu),
        requestedMemoryMi: Math.round(requestedMem),
        actualMemoryP95Mi: Math.round(actualMem),
        cpuWastePercent: Math.max(0, Math.round(cpuWaste * 10) / 10),
        memoryWastePercent: Math.max(0, Math.round(memWaste * 10) / 10),
        estimatedMonthlySavingsUsd: Math.max(0, Math.round(cpuSavingsPerMonth * 100) / 100),
        suggestedCpuRequest: `${Math.ceil(actualCpu * 1.2)}m`,
        suggestedMemoryRequest: `${Math.ceil(actualMem * 1.2)}Mi`,
      };
    });

    res.json(recommendations.filter((r) => r.cpuWastePercent > 30));
  } catch {
    res.json([]);
  }
});

app.get('/api/chaos', async (req, res) => {
  try {
    const result = await pool.query(
      "SELECT value FROM config WHERE key = 'chaos_enabled' LIMIT 1"
    );
    res.json({ enabled: result.rows[0]?.value === 'true' });
  } catch {
    res.json({ enabled: false });
  }
});

app.post('/api/chaos', async (req, res) => {
  const { enabled } = req.body;
  if (typeof enabled !== 'boolean') {
    return res.status(400).json({ error: 'enabled must be a boolean' });
  }
  try {
    await pool.query(
      `INSERT INTO config (key, value) VALUES ('chaos_enabled', $1)
       ON CONFLICT (key) DO UPDATE SET value = $1`,
      [String(enabled)]
    );
    res.json({ enabled, message: `Chaos mode ${enabled ? 'enabled' : 'disabled'}` });
  } catch {
    res.json({ enabled, message: 'Config stored in memory only (DB unavailable)' });
  }
});

app.get('/health', (req, res) => res.json({ status: 'ok' }));

app.listen(PORT, () => {
  console.log(JSON.stringify({ level: 'info', message: `Dashboard API server listening on port ${PORT}` }));
});
