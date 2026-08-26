import unittest
from unittest.mock import patch

from backend_fastapi.ai import _parse_tasks_from_ocr_text


class WorkflowUploadOCRTests(unittest.TestCase):
    @patch("backend_fastapi.ai.generate_response", return_value=None)
    def test_parse_handwritten_numbered_tasks_keeps_following_lines_as_description(self, _generate_response):
        ocr_text = """
        1. Complete the AI project feature update
        Regarding project for Task Management complete it by today
        2. Test the working of project
        Test working and give demo tomorrow
        3. Demo the project internally
        Show the demo of project by 24th July
        """

        tasks = _parse_tasks_from_ocr_text(ocr_text, "Extract tasks from handwritten note")

        self.assertEqual(tasks[0]["title"], "Complete the AI project feature update")
        self.assertEqual(tasks[0]["description"], "Regarding project for Task Management complete it by today")
        self.assertEqual(tasks[1]["title"], "Test the working of project")
        self.assertEqual(tasks[1]["description"], "Test working and give demo tomorrow")
        self.assertEqual(tasks[2]["title"], "Demo the project internally")
        self.assertEqual(tasks[2]["description"], "Show the demo of project by 24th July")

    def test_parse_task_table_uses_task_name_and_combines_row_metadata(self):
        ocr_text = """
        | Task ID | Task Name | Description | Assigned To | Deadline |
        | --- | --- | --- | --- | --- |
        | T-001 | Requirements Gathering | Meet with stakeholders to collect design, functionality, and branding needs. | Priya Sharma | 25 July 2026 |
        | T-002 | Wireframe Creation | Develop low-fidelity wireframes for homepage and key landing pages. | Rahul Mehta | 30 July 2026 |
        """

        tasks = _parse_tasks_from_ocr_text(ocr_text, "Create tasks from this document")

        self.assertEqual(
            tasks,
            [
                {
                    "title": "Requirements Gathering",
                    "description": "Meet with stakeholders to collect design, functionality, and branding needs. | Assigned To: Priya Sharma | Deadline: 25 July 2026",
                },
                {
                    "title": "Wireframe Creation",
                    "description": "Develop low-fidelity wireframes for homepage and key landing pages. | Assigned To: Rahul Mehta | Deadline: 30 July 2026",
                },
            ],
        )

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
