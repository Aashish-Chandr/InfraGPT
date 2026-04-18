import axios from 'axios';

export const apiClient = axios.create({
  baseURL: '/api',
  timeout: 10_000,
  headers: { 'Content-Type': 'application/json' },
});

// Types
export interface ClusterStats {
  nodes: { ready: number; total: number };
  pods: { running: number; desired: number; failed: number };
  cpu: { usagePercent: number };
  memory: { usagePercent: number };
  namespaces: NamespaceStats[];
}

export interface NamespaceStats {
  name: string;
  pods: number;
  cpuUsage: string;
  memoryUsage: string;
}

export interface AnomalyEvent {
  id: number;
  timestamp: string;
  service: string;
  namespace: string;
  metric: string;
  anomalyScore: number;
  severity: 'critical' | 'warning' | 'info';
  currentValue: number;
  rootCauseAnalysis: string;
}

export interface Incident {
  id: number;
  timestamp: string;
  service: string;
  namespace: string;
  metric: string;
  anomalyScore: number;
  severity: string;
  rootCauseAnalysis: string;
  healingAction: string | null;
  healingSuccess: boolean | null;
  healingDurationSeconds: number | null;
  resolvedAt: string | null;
}

export interface IncidentStats {
  totalIncidents: number;
  resolvedIncidents: number;
  mttrSeconds: number;
  incidents: Incident[];
}

export interface PodCostInfo {
  namespace: string;
  pod: string;
  container: string;
  requestedCpu: number;
  actualCpuP95: number;
  requestedMemoryMi: number;
  actualMemoryP95Mi: number;
  cpuWastePercent: number;
  memoryWastePercent: number;
  estimatedMonthlySavingsUsd: number;
  suggestedCpuRequest: string;
  suggestedMemoryRequest: string;
}

// API functions
export const fetchClusterStats = () =>
  apiClient.get<ClusterStats>('/cluster/stats').then((r) => r.data);

export const fetchAnomalies = (limit = 50) =>
  apiClient.get<AnomalyEvent[]>(`/anomalies?limit=${limit}`).then((r) => r.data);

export const fetchIncidents = () =>
  apiClient.get<IncidentStats>('/incidents').then((r) => r.data);

export const fetchCostData = () =>
  apiClient.get<PodCostInfo[]>('/cost/optimization').then((r) => r.data);

export const setChaosMode = (enabled: boolean) =>
  apiClient.post('/chaos', { enabled }).then((r) => r.data);

export const getChaosMode = () =>
  apiClient.get<{ enabled: boolean }>('/chaos').then((r) => r.data);
