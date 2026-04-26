'use strict';

// Tracing is a no-op in test mode (see tracing.js)
require('./tracing');

const express = require('express');
const axios = require('axios');
const cors = require('cors');
const helmet = require('helmet');
const rateLimit = require('express-rate-limit');
const client = require('prom-client');
const winston = require('winston');

// ─── Logger ───────────────────────────────────────────────────────────────────

const logger = winston.createLogger({
  level: process.env.LOG_LEVEL || 'info',
  format: winston.format.combine(
    winston.format.timestamp(),
    winston.format.errors({ stack: true }),
    winston.format.json()
  ),
  defaultMeta: { service: 'infragpt-frontend' },
  transports: [new winston.transports.Console()],
});

// ─── Prometheus Metrics ───────────────────────────────────────────────────────

const register = new client.Registry();
client.collectDefaultMetrics({ register });

const httpRequestDuration = new client.Histogram({
  name: 'http_request_duration_seconds',
  help: 'Duration of HTTP requests in seconds',
  labelNames: ['method', 'route', 'status_code'],
  buckets: [0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1, 2, 5],
  registers: [register],
});

const httpRequestTotal = new client.Counter({
  name: 'http_requests_total',
  help: 'Total number of HTTP requests',
  labelNames: ['method', 'route', 'status_code'],
  registers: [register],
});

const backendCallDuration = new client.Histogram({
  name: 'backend_call_duration_seconds',
  help: 'Duration of calls to backend service',
  labelNames: ['endpoint', 'status'],
  buckets: [0.01, 0.05, 0.1, 0.5, 1, 2, 5],
  registers: [register],
});

// ─── App Setup ────────────────────────────────────────────────────────────────

const app = express();
const PORT = process.env.PORT || 3000;
const BACKEND_URL = process.env.BACKEND_URL || 'http://backend:8000';

app.use(helmet());
app.use(cors());
app.use(express.json({ limit: '1mb' }));

const limiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 1000,
  standardHeaders: true,
  legacyHeaders: false,
});
app.use(limiter);

// ─── Metrics Middleware ───────────────────────────────────────────────────────

app.use((req, res, next) => {
  const start = Date.now();
  res.on('finish', () => {
    const duration = (Date.now() - start) / 1000;
    const route = req.route ? req.route.path : req.path;
    httpRequestDuration.observe(
      { method: req.method, route, status_code: res.statusCode },
      duration
    );
    httpRequestTotal.inc({
      method: req.method,
      route,
      status_code: res.statusCode,
    });
  });
  next();
});

// ─── Routes ───────────────────────────────────────────────────────────────────

app.get('/health', (_req, res) => {
  res.json({
    status: 'ok',
    service: 'infragpt-frontend',
    version: process.env.APP_VERSION || '1.0.0',
    timestamp: new Date().toISOString(),
  });
});

app.get('/ready', async (_req, res) => {
  try {
    await axios.get(`${BACKEND_URL}/health`, { timeout: 2000 });
    res.json({ status: 'ready' });
  } catch (err) {
    logger.warn('Backend not ready', { error: err.message });
    res.status(503).json({ status: 'not ready', reason: 'backend unavailable' });
  }
});

app.get('/metrics', async (_req, res) => {
  res.set('Content-Type', register.contentType);
  res.end(await register.metrics());
});

app.get('/api/items', async (req, res) => {
  const timer = backendCallDuration.startTimer({ endpoint: '/items' });
  try {
    const response = await axios.get(`${BACKEND_URL}/items`, {
      timeout: 5000,
      headers: {
        'X-Request-ID':
          req.headers['x-request-id'] || generateRequestId(),
      },
    });
    timer({ status: 'success' });
    logger.info('Fetched items from backend', {
      count: response.data.length,
    });
    res.json(response.data);
  } catch (err) {
    timer({ status: 'error' });
    logger.error('Failed to fetch items', { error: err.message });
    res.status(502).json({ error: 'Failed to fetch items from backend' });
  }
});

app.post('/api/items', async (req, res) => {
  const timer = backendCallDuration.startTimer({ endpoint: '/items' });
  try {
    const response = await axios.post(`${BACKEND_URL}/items`, req.body, {
      timeout: 5000,
    });
    timer({ status: 'success' });
    res.status(201).json(response.data);
  } catch (err) {
    timer({ status: 'error' });
    logger.error('Failed to create item', { error: err.message });
    res.status(502).json({ error: 'Failed to create item' });
  }
});

app.get('/api/stats', async (_req, res) => {
  const timer = backendCallDuration.startTimer({ endpoint: '/stats' });
  try {
    const response = await axios.get(`${BACKEND_URL}/stats`, {
      timeout: 5000,
    });
    timer({ status: 'success' });
    res.json(response.data);
  } catch (err) {
    timer({ status: 'error' });
    logger.error('Failed to fetch stats', { error: err.message });
    res.status(502).json({ error: 'Failed to fetch stats' });
  }
});

// ─── Error Handler ────────────────────────────────────────────────────────────

// eslint-disable-next-line no-unused-vars
app.use((err, _req, res, _next) => {
  logger.error('Unhandled error', { error: err.message, stack: err.stack });
  res.status(500).json({ error: 'Internal server error' });
});

// ─── Helpers ──────────────────────────────────────────────────────────────────

function generateRequestId() {
  return Math.random().toString(36).substring(2, 15);
}

// ─── Start ────────────────────────────────────────────────────────────────────

// Only listen when run directly, not when required by tests
if (require.main === module) {
  const server = app.listen(PORT, () => {
    logger.info(`Frontend service listening on port ${PORT}`);
  });

  process.on('SIGTERM', () => {
    logger.info('SIGTERM received, shutting down gracefully');
    server.close(() => {
      logger.info('HTTP server closed');
      process.exit(0);
    });
  });
}

module.exports = app;
