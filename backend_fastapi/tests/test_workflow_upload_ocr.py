import unittest
from unittest.mock import patch

from backend_fastapi.ai import _parse_tasks_from_ocr_text


class WorkflowUploadOCRTests(unittest.TestCase):
    def test_parse_tasks_from_ocr_text_falls_back_to_line_items(self):
        ocr_text = """
        Review onboarding doc
        Update payroll policy
        Prepare sprint summary
        """

        tasks = _parse_tasks_from_ocr_text(ocr_text, "Create tasks from this document")

        self.assertEqual(len(tasks), 3)
        self.assertEqual(tasks[0]["title"], "Review onboarding doc")
        self.assertEqual(tasks[0]["description"], "Review onboarding doc")

    def test_parse_tasks_from_ocr_text_uses_mistral_json_output(self):
        ocr_text = "Review onboarding document and collect the sign-off list"

        with patch("backend_fastapi.ai.generate_response", return_value='[{"title": "Review onboarding", "description": "Review the onboarding document and collect the required sign-off list."}]'):
            tasks = _parse_tasks_from_ocr_text(ocr_text, "Create tasks from this document")

        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["title"], "Review onboarding")
        self.assertEqual(tasks[0]["description"], "Review the onboarding document and collect the required sign-off list.")


if __name__ == "__main__":
    unittest.main()
