'use strict';

process.env.NODE_ENV = 'test';

const request = require('supertest');

// Mock axios before requiring the app
jest.mock('axios');
const axios = require('axios');

// Require app AFTER setting NODE_ENV=test so tracing is skipped
const app = require('../index');

afterAll((done) => {
  // Close the server so Jest can exit cleanly
  if (app.listening) {
    app.close(done);
  } else {
    done();
  }
});

describe('GET /health', () => {
  it('returns 200 with status ok', async () => {
    const res = await request(app).get('/health');
    expect(res.status).toBe(200);
    expect(res.body.status).toBe('ok');
    expect(res.body.service).toBe('infragpt-frontend');
  });
});

describe('GET /metrics', () => {
  it('returns prometheus metrics text', async () => {
    const res = await request(app).get('/metrics');
    expect(res.status).toBe(200);
    expect(res.text).toContain('http_requests_total');
  });
});

describe('GET /api/items', () => {
  it('proxies to backend and returns items', async () => {
    axios.get.mockResolvedValueOnce({ data: [{ id: 1, name: 'test' }] });
    const res = await request(app).get('/api/items');
    expect(res.status).toBe(200);
    expect(Array.isArray(res.body)).toBe(true);
  });

  it('returns 502 when backend is unavailable', async () => {
    axios.get.mockRejectedValueOnce(new Error('Connection refused'));
    const res = await request(app).get('/api/items');
    expect(res.status).toBe(502);
  });
});
