"""
GEO Weekly Intelligence Digest API Tests
Tests for POST /api/geo-weekly-report/generate and GET /api/geo-weekly-report endpoints.
Features tested:
- Weekly digest generation with highlights, risks, opportunities, recommendations
- Duplicate prevention (same week returns status=duplicate)
- Report storage and retrieval
- Response structure validation
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestGeoWeeklyReportGenerate:
    """Tests for POST /api/geo-weekly-report/generate endpoint"""

    def test_generate_endpoint_exists(self):
        """POST /geo-weekly-report/generate endpoint should exist and respond"""
        response = requests.post(f"{BASE_URL}/api/geo-weekly-report/generate")
        # Should return 200 (either ok or duplicate status)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print(f"PASS: POST /geo-weekly-report/generate endpoint exists, status={response.status_code}")

    def test_generate_returns_valid_json(self):
        """POST /geo-weekly-report/generate should return valid JSON"""
        response = requests.post(f"{BASE_URL}/api/geo-weekly-report/generate")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict), "Response should be a JSON object"
        print(f"PASS: Response is valid JSON: {list(data.keys())}")

    def test_generate_returns_status_field(self):
        """Response should contain status field (ok or duplicate)"""
        response = requests.post(f"{BASE_URL}/api/geo-weekly-report/generate")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data, "Response should contain 'status' field"
        assert data["status"] in ["ok", "duplicate"], f"Status should be 'ok' or 'duplicate', got: {data['status']}"
        print(f"PASS: Status field present with value: {data['status']}")

    def test_generate_duplicate_prevention(self):
        """Calling generate twice for same week should return status=duplicate"""
        # First call
        response1 = requests.post(f"{BASE_URL}/api/geo-weekly-report/generate")
        assert response1.status_code == 200
        data1 = response1.json()
        
        # Second call should return duplicate (since report already exists)
        response2 = requests.post(f"{BASE_URL}/api/geo-weekly-report/generate")
        assert response2.status_code == 200
        data2 = response2.json()
        
        # At least one should be duplicate (since a report already exists per context)
        assert data2["status"] == "duplicate", f"Second call should return duplicate, got: {data2['status']}"
        print(f"PASS: Duplicate prevention working - second call returned status=duplicate")

    def test_generate_returns_week_start(self):
        """Response should contain week_start field"""
        response = requests.post(f"{BASE_URL}/api/geo-weekly-report/generate")
        assert response.status_code == 200
        data = response.json()
        assert "week_start" in data, "Response should contain 'week_start' field"
        assert data["week_start"] is not None, "week_start should not be None"
        print(f"PASS: week_start field present: {data['week_start']}")


class TestGeoWeeklyReportGet:
    """Tests for GET /api/geo-weekly-report endpoint"""

    def test_get_endpoint_exists(self):
        """GET /geo-weekly-report endpoint should exist and respond"""
        response = requests.get(f"{BASE_URL}/api/geo-weekly-report")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print(f"PASS: GET /geo-weekly-report endpoint exists, status={response.status_code}")

    def test_get_returns_reports_array(self):
        """GET should return reports array"""
        response = requests.get(f"{BASE_URL}/api/geo-weekly-report")
        assert response.status_code == 200
        data = response.json()
        assert "reports" in data, "Response should contain 'reports' field"
        assert isinstance(data["reports"], list), "reports should be an array"
        print(f"PASS: reports array present with {len(data['reports'])} reports")

    def test_get_returns_count_field(self):
        """GET should return count field"""
        response = requests.get(f"{BASE_URL}/api/geo-weekly-report")
        assert response.status_code == 200
        data = response.json()
        assert "count" in data, "Response should contain 'count' field"
        assert isinstance(data["count"], int), "count should be an integer"
        assert data["count"] == len(data["reports"]), "count should match reports array length"
        print(f"PASS: count field present: {data['count']}")

    def test_get_report_has_required_fields(self):
        """Each report should have required fields: id, week_start, week_end, summary, top_cities, top_variants, global_avg_cvr, email_sent, created_at"""
        response = requests.get(f"{BASE_URL}/api/geo-weekly-report")
        assert response.status_code == 200
        data = response.json()
        
        if len(data["reports"]) == 0:
            pytest.skip("No reports available to test structure")
        
        report = data["reports"][0]
        required_fields = ["id", "week_start", "week_end", "summary", "top_cities", "top_variants", "global_avg_cvr", "email_sent", "created_at"]
        
        for field in required_fields:
            assert field in report, f"Report should contain '{field}' field"
        
        print(f"PASS: Report has all required fields: {required_fields}")

    def test_get_report_summary_structure(self):
        """Report summary should have highlights, risks, opportunities, recommendations arrays"""
        response = requests.get(f"{BASE_URL}/api/geo-weekly-report")
        assert response.status_code == 200
        data = response.json()
        
        if len(data["reports"]) == 0:
            pytest.skip("No reports available to test summary structure")
        
        report = data["reports"][0]
        summary = report.get("summary", {})
        
        summary_fields = ["highlights", "risks", "opportunities", "recommendations"]
        for field in summary_fields:
            assert field in summary, f"Summary should contain '{field}' array"
            assert isinstance(summary[field], list), f"summary.{field} should be an array"
        
        print(f"PASS: Summary has all required arrays: {summary_fields}")
        print(f"  - highlights: {len(summary['highlights'])} items")
        print(f"  - risks: {len(summary['risks'])} items")
        print(f"  - opportunities: {len(summary['opportunities'])} items")
        print(f"  - recommendations: {len(summary['recommendations'])} items")

    def test_get_report_top_cities_structure(self):
        """top_cities should be an array with city data"""
        response = requests.get(f"{BASE_URL}/api/geo-weekly-report")
        assert response.status_code == 200
        data = response.json()
        
        if len(data["reports"]) == 0:
            pytest.skip("No reports available to test top_cities structure")
        
        report = data["reports"][0]
        top_cities = report.get("top_cities", [])
        
        assert isinstance(top_cities, list), "top_cities should be an array"
        
        if len(top_cities) > 0:
            city = top_cities[0]
            # Check for expected city fields
            expected_fields = ["city", "cvr", "views"]
            for field in expected_fields:
                assert field in city, f"City entry should contain '{field}' field"
            print(f"PASS: top_cities has {len(top_cities)} cities with proper structure")
        else:
            print(f"PASS: top_cities is empty array (no data)")

    def test_get_report_top_variants_structure(self):
        """top_variants should be an array with variant data"""
        response = requests.get(f"{BASE_URL}/api/geo-weekly-report")
        assert response.status_code == 200
        data = response.json()
        
        if len(data["reports"]) == 0:
            pytest.skip("No reports available to test top_variants structure")
        
        report = data["reports"][0]
        top_variants = report.get("top_variants", [])
        
        assert isinstance(top_variants, list), "top_variants should be an array"
        
        if len(top_variants) > 0:
            variant = top_variants[0]
            expected_fields = ["variant", "cvr", "views"]
            for field in expected_fields:
                assert field in variant, f"Variant entry should contain '{field}' field"
            print(f"PASS: top_variants has {len(top_variants)} variants with proper structure")
        else:
            print(f"PASS: top_variants is empty array (no data)")

    def test_get_report_global_avg_cvr_is_numeric(self):
        """global_avg_cvr should be a numeric value"""
        response = requests.get(f"{BASE_URL}/api/geo-weekly-report")
        assert response.status_code == 200
        data = response.json()
        
        if len(data["reports"]) == 0:
            pytest.skip("No reports available to test global_avg_cvr")
        
        report = data["reports"][0]
        global_avg_cvr = report.get("global_avg_cvr")
        
        assert global_avg_cvr is not None, "global_avg_cvr should not be None"
        assert isinstance(global_avg_cvr, (int, float)), f"global_avg_cvr should be numeric, got {type(global_avg_cvr)}"
        print(f"PASS: global_avg_cvr is numeric: {global_avg_cvr}")

    def test_get_report_email_sent_is_boolean(self):
        """email_sent should be a boolean value"""
        response = requests.get(f"{BASE_URL}/api/geo-weekly-report")
        assert response.status_code == 200
        data = response.json()
        
        if len(data["reports"]) == 0:
            pytest.skip("No reports available to test email_sent")
        
        report = data["reports"][0]
        email_sent = report.get("email_sent")
        
        assert email_sent is not None, "email_sent should not be None"
        assert isinstance(email_sent, bool), f"email_sent should be boolean, got {type(email_sent)}"
        print(f"PASS: email_sent is boolean: {email_sent}")

    def test_get_limit_parameter(self):
        """GET /geo-weekly-report?limit=1 should respect limit parameter"""
        response = requests.get(f"{BASE_URL}/api/geo-weekly-report?limit=1")
        assert response.status_code == 200
        data = response.json()
        
        assert "reports" in data, "Response should contain 'reports' field"
        assert len(data["reports"]) <= 1, f"With limit=1, should return at most 1 report, got {len(data['reports'])}"
        assert data["count"] <= 1, f"count should be at most 1 with limit=1, got {data['count']}"
        print(f"PASS: limit=1 parameter respected, returned {len(data['reports'])} report(s)")


class TestSummaryContent:
    """Tests for summary content quality"""

    def test_summary_highlights_content(self):
        """Summary highlights should include meaningful content"""
        response = requests.get(f"{BASE_URL}/api/geo-weekly-report")
        assert response.status_code == 200
        data = response.json()
        
        if len(data["reports"]) == 0:
            pytest.skip("No reports available to test highlights content")
        
        report = data["reports"][0]
        highlights = report.get("summary", {}).get("highlights", [])
        
        # Highlights should have at least one item (even if "No significant changes")
        assert len(highlights) >= 1, "Highlights should have at least one item"
        
        # Check for expected content patterns
        highlights_text = " ".join(highlights).lower()
        has_performer_mention = "performer" in highlights_text or "cvr" in highlights_text or "variant" in highlights_text or "no significant" in highlights_text
        assert has_performer_mention, f"Highlights should mention performers, CVR, variants, or no changes. Got: {highlights}"
        print(f"PASS: Highlights have meaningful content: {highlights[:2]}...")

    def test_summary_recommendations_content(self):
        """Summary recommendations should include actionable items"""
        response = requests.get(f"{BASE_URL}/api/geo-weekly-report")
        assert response.status_code == 200
        data = response.json()
        
        if len(data["reports"]) == 0:
            pytest.skip("No reports available to test recommendations content")
        
        report = data["reports"][0]
        recommendations = report.get("summary", {}).get("recommendations", [])
        
        if len(recommendations) > 0:
            # Check for action words
            recs_text = " ".join(recommendations).lower()
            has_action = any(word in recs_text for word in ["scale", "optimize", "expand", "monitor", "rework", "drop", "new"])
            assert has_action, f"Recommendations should include action words. Got: {recommendations}"
            print(f"PASS: Recommendations have actionable content: {recommendations[:2]}...")
        else:
            print(f"PASS: No recommendations (may be expected if no data)")


class TestWeekDates:
    """Tests for week date handling"""

    def test_week_start_format(self):
        """week_start should be in valid date format"""
        response = requests.get(f"{BASE_URL}/api/geo-weekly-report")
        assert response.status_code == 200
        data = response.json()
        
        if len(data["reports"]) == 0:
            pytest.skip("No reports available to test week_start format")
        
        report = data["reports"][0]
        week_start = report.get("week_start")
        
        # Should be in YYYY-MM-DD format
        import re
        date_pattern = r'^\d{4}-\d{2}-\d{2}$'
        assert re.match(date_pattern, week_start), f"week_start should be YYYY-MM-DD format, got: {week_start}"
        print(f"PASS: week_start is valid date format: {week_start}")

    def test_week_end_format(self):
        """week_end should be in valid date format"""
        response = requests.get(f"{BASE_URL}/api/geo-weekly-report")
        assert response.status_code == 200
        data = response.json()
        
        if len(data["reports"]) == 0:
            pytest.skip("No reports available to test week_end format")
        
        report = data["reports"][0]
        week_end = report.get("week_end")
        
        # Should be in YYYY-MM-DD format
        import re
        date_pattern = r'^\d{4}-\d{2}-\d{2}$'
        assert re.match(date_pattern, week_end), f"week_end should be YYYY-MM-DD format, got: {week_end}"
        print(f"PASS: week_end is valid date format: {week_end}")

    def test_week_dates_are_7_days_apart(self):
        """week_end should be approximately 7 days after week_start"""
        response = requests.get(f"{BASE_URL}/api/geo-weekly-report")
        assert response.status_code == 200
        data = response.json()
        
        if len(data["reports"]) == 0:
            pytest.skip("No reports available to test week dates")
        
        report = data["reports"][0]
        from datetime import datetime
        
        week_start = datetime.strptime(report["week_start"], "%Y-%m-%d")
        week_end = datetime.strptime(report["week_end"], "%Y-%m-%d")
        
        days_diff = (week_end - week_start).days
        assert 6 <= days_diff <= 8, f"Week should be ~7 days, got {days_diff} days"
        print(f"PASS: Week dates are {days_diff} days apart")


class TestReportId:
    """Tests for report ID handling"""

    def test_report_id_is_uuid(self):
        """Report id should be a valid UUID"""
        response = requests.get(f"{BASE_URL}/api/geo-weekly-report")
        assert response.status_code == 200
        data = response.json()
        
        if len(data["reports"]) == 0:
            pytest.skip("No reports available to test report id")
        
        report = data["reports"][0]
        report_id = report.get("id")
        
        import re
        uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        assert re.match(uuid_pattern, report_id, re.IGNORECASE), f"Report id should be UUID format, got: {report_id}"
        print(f"PASS: Report id is valid UUID: {report_id}")


class TestCreatedAt:
    """Tests for created_at timestamp"""

    def test_created_at_is_iso_format(self):
        """created_at should be in ISO format"""
        response = requests.get(f"{BASE_URL}/api/geo-weekly-report")
        assert response.status_code == 200
        data = response.json()
        
        if len(data["reports"]) == 0:
            pytest.skip("No reports available to test created_at")
        
        report = data["reports"][0]
        created_at = report.get("created_at")
        
        assert created_at is not None, "created_at should not be None"
        # Should contain date and time components
        assert "T" in created_at or "-" in created_at, f"created_at should be ISO format, got: {created_at}"
        print(f"PASS: created_at is ISO format: {created_at}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
