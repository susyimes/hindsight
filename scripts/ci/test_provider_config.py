from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from provider_config import detect_provider_configuration, render_summary, write_github_files


def _vertex_credentials() -> str:
    return (
        '{"type":"service_account","project_id":"test-project","client_email":"ci@example.invalid",'
        '"private_key":"synthetic-private-key","token_uri":"https://example.invalid/token"}'
    )


class ProviderConfigurationTests(unittest.TestCase):
    def test_same_repository_without_secrets_is_unconfigured(self) -> None:
        configuration = detect_provider_configuration(
            {
                "GITHUB_REPOSITORY": "owner/repository",
                "PR_HEAD_REPOSITORY": "owner/repository",
            }
        )

        self.assertFalse(configuration.vertexai.configured)
        self.assertFalse(configuration.cohere.configured)
        self.assertFalse(configuration.slim.configured)

    def test_partial_configuration_uses_only_complete_provider_paths(self) -> None:
        configuration = detect_provider_configuration({"GCP_VERTEXAI_CREDENTIALS": _vertex_credentials()})

        self.assertTrue(configuration.vertexai.configured)
        self.assertFalse(configuration.cohere.configured)
        self.assertFalse(configuration.slim.configured)

    def test_incomplete_vertex_credentials_are_rejected(self) -> None:
        configuration = detect_provider_configuration(
            {"GCP_VERTEXAI_CREDENTIALS": '{"type":"service_account","project_id":"test-project"}'}
        )

        self.assertFalse(configuration.vertexai.configured)
        self.assertIn("client_email", configuration.vertexai.reason)
        self.assertNotIn("test-project", configuration.vertexai.reason)

    def test_null_vertex_fields_are_rejected(self) -> None:
        configuration = detect_provider_configuration(
            {
                "GCP_VERTEXAI_CREDENTIALS": (
                    '{"type":"service_account","project_id":null,"client_email":"ci@example.invalid",'
                    '"private_key":"synthetic-private-key","token_uri":"https://example.invalid/token"}'
                )
            }
        )

        self.assertFalse(configuration.vertexai.configured)
        self.assertIn("project_id", configuration.vertexai.reason)

    def test_complete_configuration_enables_each_provider_path(self) -> None:
        configuration = detect_provider_configuration(
            {
                "GCP_VERTEXAI_CREDENTIALS": _vertex_credentials(),
                "COHERE_API_KEY": "cohere-secret",
                "GEMINI_API_KEY": "gemini-secret",
                "OPENAI_API_KEY": "openai-secret",
                "GROQ_API_KEY": "groq-secret",
                "AWS_ACCESS_KEY_ID": "aws-id",
                "AWS_SECRET_ACCESS_KEY": "aws-secret",
                "AWS_REGION_NAME": "us-test-1",
            }
        )

        self.assertTrue(all(check.configured for _, check in configuration.named_checks()))

    def test_outputs_and_summary_do_not_expose_values(self) -> None:
        secrets = {
            "GCP_VERTEXAI_CREDENTIALS": _vertex_credentials(),
            "COHERE_API_KEY": "cohere-secret",
            "OPENAI_API_KEY": "openai-secret",
        }
        configuration = detect_provider_configuration(secrets)

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "output"
            summary_path = Path(temp_dir) / "summary"
            write_github_files(configuration, str(output_path), str(summary_path))
            rendered = output_path.read_text(encoding="utf-8") + summary_path.read_text(encoding="utf-8")

        for secret in secrets.values():
            self.assertNotIn(secret, rendered)
        self.assertEqual(render_summary(configuration), rendered[rendered.index("### Provider configuration") :])


if __name__ == "__main__":
    unittest.main()
