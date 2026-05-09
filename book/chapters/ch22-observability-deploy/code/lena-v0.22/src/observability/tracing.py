"""OpenTelemetry 接入。

选型：OTLP exporter 支持所有主流后端，换后端只改 endpoint，不改业务代码。

本地开发后端（Jaeger all-in-one）：
    docker run --rm -p 16686:16686 -p 4317:4317 jaegertracing/all-in-one

生产迁移：
    - AWS X-Ray：用 AWS ADOT Collector，endpoint 改为 collector sidecar 地址
    - Honeycomb：endpoint 改为 api.honeycomb.io:443，加 x-honeycomb-team header
    - Grafana Cloud：endpoint 改为 tempo endpoint

用法：
    from lena.observability.tracing import setup_tracing
    from opentelemetry import trace

    tracer = setup_tracing()

    with tracer.start_as_current_span("llm_call") as span:
        span.set_attribute("model", "claude-sonnet-4-6")
        span.set_attribute("input_tokens", 4230)
        result = call_llm(...)
        span.set_attribute("output_tokens", result.usage.output_tokens)
"""
import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def setup_tracing(
    service_name: str = "lena",
    service_version: str = "0.22.0",
    otlp_endpoint: str | None = None,
) -> trace.Tracer:
    """初始化 OTel tracer，导出到 OTLP。

    Args:
        service_name: 服务名，显示在 Jaeger UI 的服务列表中
        service_version: 服务版本，便于对比版本间性能变化
        otlp_endpoint: OTLP gRPC endpoint，默认从 OTEL_EXPORTER_OTLP_ENDPOINT
                       环境变量读取，缺省 http://localhost:4317

    Returns:
        配置好的 Tracer，业务代码用这个对象创建 span
    """
    if otlp_endpoint is None:
        otlp_endpoint = os.environ.get(
            "OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"
        )

    resource = Resource.create({
        "service.name": service_name,
        "service.version": service_version,
    })

    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    return trace.get_tracer(service_name)
