#!/usr/bin/env python3
"""Detect CI provider configuration without emitting credential values."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ConfigurationCheck:
    configured: bool
    reason: str


@dataclass(frozen=True)
class ProviderConfiguration:
    vertexai: ConfigurationCheck
    cohere: ConfigurationCheck
    gemini: ConfigurationCheck
    openai: ConfigurationCheck
    groq: ConfigurationCheck
    bedrock: ConfigurationCheck

    @property
    def slim(self) -> ConfigurationCheck:
        if self.vertexai.configured and self.cohere.configured:
            return ConfigurationCheck(True, "complete Vertex AI and Cohere configuration")

        missing = []
        if not self.vertexai.configured:
            missing.append("Vertex AI")
        if not self.cohere.configured:
            missing.append("Cohere")
        return ConfigurationCheck(False, f"incomplete {' and '.join(missing)} configuration")

    @property
    def litellmrouter(self) -> ConfigurationCheck:
        if self.openai.configured:
            return ConfigurationCheck(True, "complete OpenAI-backed router configuration")
        return ConfigurationCheck(False, "OpenAI API key is unavailable")

    def named_checks(self) -> tuple[tuple[str, ConfigurationCheck], ...]:
        return (
            ("vertexai", self.vertexai),
            ("cohere", self.cohere),
            ("slim", self.slim),
            ("gemini", self.gemini),
            ("openai", self.openai),
            ("groq", self.groq),
            ("bedrock", self.bedrock),
            ("litellmrouter", self.litellmrouter),
        )


_VERTEX_REQUIRED_FIELDS = ("project_id", "client_email", "private_key", "token_uri")


def _check_nonempty(environment: Mapping[str, str], variable: str, label: str) -> ConfigurationCheck:
    if environment.get(variable, "").strip():
        return ConfigurationCheck(True, f"{label} is configured")
    return ConfigurationCheck(False, f"{label} is unavailable")


def _check_vertexai(environment: Mapping[str, str]) -> ConfigurationCheck:
    raw_credentials = environment.get("GCP_VERTEXAI_CREDENTIALS", "").strip()
    if not raw_credentials:
        return ConfigurationCheck(False, "service-account credential JSON is unavailable")

    try:
        credentials = json.loads(raw_credentials)
    except json.JSONDecodeError:
        return ConfigurationCheck(False, "service-account credential JSON is invalid")

    if not isinstance(credentials, dict):
        return ConfigurationCheck(False, "service-account credential JSON is not an object")

    if credentials.get("type") != "service_account":
        return ConfigurationCheck(False, "credential JSON is not a service-account configuration")

    missing = [
        field
        for field in _VERTEX_REQUIRED_FIELDS
        if not isinstance(credentials.get(field), str) or not credentials[field].strip()
    ]
    if missing:
        return ConfigurationCheck(False, f"service-account credential JSON is missing: {', '.join(missing)}")

    return ConfigurationCheck(True, "complete service-account credential JSON")


def _check_bedrock(environment: Mapping[str, str]) -> ConfigurationCheck:
    required = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION_NAME")
    missing = [variable for variable in required if not environment.get(variable, "").strip()]
    if missing:
        return ConfigurationCheck(False, f"configuration is missing: {', '.join(missing)}")
    return ConfigurationCheck(True, "complete access-key and region configuration")


def detect_provider_configuration(environment: Mapping[str, str]) -> ProviderConfiguration:
    """Return configuration state based only on required provider values."""
    return ProviderConfiguration(
        vertexai=_check_vertexai(environment),
        cohere=_check_nonempty(environment, "COHERE_API_KEY", "Cohere API key"),
        gemini=_check_nonempty(environment, "GEMINI_API_KEY", "Gemini API key"),
        openai=_check_nonempty(environment, "OPENAI_API_KEY", "OpenAI API key"),
        groq=_check_nonempty(environment, "GROQ_API_KEY", "Groq API key"),
        bedrock=_check_bedrock(environment),
    )


def render_summary(configuration: ProviderConfiguration) -> str:
    lines = [
        "### Provider configuration",
        "",
        "Configuration is evaluated from required values; repository topology is not used.",
        "No credential values are included below.",
        "",
        "| Provider path | Status | Reason |",
        "| --- | --- | --- |",
    ]
    for name, check in configuration.named_checks():
        status = "configured" if check.configured else "unavailable"
        lines.append(f"| {name} | {status} | {check.reason} |")
    lines.extend(
        [
            "",
            "Unavailable real-provider suites report an explicit skip. Approved integration paths use local/mock fallback.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_github_files(
    configuration: ProviderConfiguration,
    output_path: str | None,
    summary_path: str | None,
) -> None:
    if output_path:
        with Path(output_path).open("a", encoding="utf-8") as output_file:
            for name, check in configuration.named_checks():
                output_file.write(f"{name}={str(check.configured).lower()}\n")

    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as summary_file:
            summary_file.write(render_summary(configuration))


def main() -> None:
    configuration = detect_provider_configuration(os.environ)
    write_github_files(configuration, os.getenv("GITHUB_OUTPUT"), os.getenv("GITHUB_STEP_SUMMARY"))


if __name__ == "__main__":
    main()
