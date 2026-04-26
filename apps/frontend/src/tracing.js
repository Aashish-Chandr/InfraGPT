'use strict';

// OpenTelemetry tracing — only initialised when not in test environment
if (process.env.NODE_ENV !== 'test') {
  try {
    const { NodeSDK } = require('@opentelemetry/sdk-node');
    const {
      getNodeAutoInstrumentations,
    } = require('@opentelemetry/auto-instrumentations-node');
    const {
      OTLPTraceExporter,
    } = require('@opentelemetry/exporter-otlp-http');
    const { Resource } = require('@opentelemetry/resources');
    const {
      SemanticResourceAttributes,
    } = require('@opentelemetry/semantic-conventions');

    const traceExporter = new OTLPTraceExporter({
      url:
        process.env.OTEL_EXPORTER_OTLP_ENDPOINT ||
        'http://jaeger-collector:4318/v1/traces',
    });

    const sdk = new NodeSDK({
      resource: new Resource({
        [SemanticResourceAttributes.SERVICE_NAME]: 'infragpt-frontend',
        [SemanticResourceAttributes.SERVICE_VERSION]:
          process.env.APP_VERSION || '1.0.0',
        environment: process.env.NODE_ENV || 'production',
      }),
      traceExporter,
      instrumentations: [
        getNodeAutoInstrumentations({
          '@opentelemetry/instrumentation-http': { enabled: true },
          '@opentelemetry/instrumentation-express': { enabled: true },
        }),
      ],
    });

    sdk.start();

    process.on('SIGTERM', () => {
      sdk.shutdown().then(() => process.exit(0));
    });
  } catch (err) {
    // Tracing is best-effort — never crash the app if it fails to init
    console.warn('OpenTelemetry init failed:', err.message);
  }
}

module.exports = {};
