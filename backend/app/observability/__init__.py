"""Logs, metrics, traces and error reports.

A load balancer routing on readiness is only half of operability. The other half is being
able to answer, after the fact, *which* instance served the slow request and *what* it was
waiting on. That is what this package is for.

Every piece of it degrades to nothing rather than failing: an instance with no OTLP
collector, no Sentry DSN and no Prometheus scraper runs exactly as it did before, and none
of the optional dependencies are required to import the application.
"""
