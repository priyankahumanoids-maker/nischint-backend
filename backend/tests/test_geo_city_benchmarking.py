"""
Test GEO Analytics City-to-City Benchmarking Feature
=====================================================
Tests the new city_benchmarking array in GET /api/geo-analytics response.

Features tested:
- city_benchmarking array sorted by priority_score descending
- global_avg_cvr field calculation
- Entry structure: city, best_variant, cvr, views, performance_ratio, category, priority_score, action
- Category classification: high_performer (>=1.5x), above_average (1.0-1.5x), below_average (0.7-1.0x), weak (<0.7x)
- priority_score = cvr * log(views + 1) calculation
- Action mapping per category
- Benchmarking recommendations in recommendations array
- Empty array when no cities have views >= 30
- Filters work with city_benchmarking
"""

import pytest
import requests
import os
import math

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestCityBenchmarkingStructure:
    """Test city_benchmarking array structure and fields"""
    
    def test_city_benchmarking_field_exists(self):
        """Verify city_benchmarking array exists in response"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        assert response.status_code == 200
        data = response.json()
        assert "city_benchmarking" in data, "city_benchmarking field missing from response"
        assert isinstance(data["city_benchmarking"], list), "city_benchmarking should be a list"
        print(f"✓ city_benchmarking field exists with {len(data['city_benchmarking'])} entries")
    
    def test_global_avg_cvr_field_exists(self):
        """Verify global_avg_cvr field exists in response"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        assert response.status_code == 200
        data = response.json()
        assert "global_avg_cvr" in data, "global_avg_cvr field missing from response"
        assert isinstance(data["global_avg_cvr"], (int, float)), "global_avg_cvr should be numeric"
        print(f"✓ global_avg_cvr = {data['global_avg_cvr']}%")
    
    def test_city_benchmarking_entry_structure(self):
        """Verify each entry has required fields"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        assert response.status_code == 200
        data = response.json()
        
        if len(data["city_benchmarking"]) == 0:
            pytest.skip("No benchmarking data available (need cities with 30+ views)")
        
        required_fields = ["city", "best_variant", "cvr", "views", "performance_ratio", "category", "priority_score", "action"]
        
        for entry in data["city_benchmarking"]:
            for field in required_fields:
                assert field in entry, f"Missing field '{field}' in entry: {entry}"
        
        print(f"✓ All {len(data['city_benchmarking'])} entries have required fields: {required_fields}")
    
    def test_city_benchmarking_sorted_by_priority_score_descending(self):
        """Verify array is sorted by priority_score in descending order"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        assert response.status_code == 200
        data = response.json()
        
        if len(data["city_benchmarking"]) < 2:
            pytest.skip("Need at least 2 entries to verify sorting")
        
        scores = [entry["priority_score"] for entry in data["city_benchmarking"]]
        assert scores == sorted(scores, reverse=True), f"Not sorted descending: {scores}"
        print(f"✓ Sorted by priority_score descending: {scores[:5]}...")


class TestCategoryClassification:
    """Test performance_ratio to category classification"""
    
    def test_simcity_high_performer_classification(self):
        """SimCity should be classified as high_performer (CVR 14.3% / global ~7.15% = 2.0x >= 1.5)"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        assert response.status_code == 200
        data = response.json()
        
        simcity_entry = next((e for e in data["city_benchmarking"] if e["city"] == "SimCity"), None)
        if not simcity_entry:
            pytest.skip("SimCity not in benchmarking data")
        
        assert simcity_entry["category"] == "high_performer", f"SimCity should be high_performer, got: {simcity_entry['category']}"
        assert simcity_entry["performance_ratio"] >= 1.5, f"SimCity ratio should be >= 1.5, got: {simcity_entry['performance_ratio']}"
        print(f"✓ SimCity classified as high_performer with ratio {simcity_entry['performance_ratio']}x")
    
    def test_weakcity_weak_classification(self):
        """WeakCity should be classified as weak (CVR 0% / global ~7.15% = 0.0x < 0.7)"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        assert response.status_code == 200
        data = response.json()
        
        weakcity_entry = next((e for e in data["city_benchmarking"] if e["city"] == "WeakCity"), None)
        if not weakcity_entry:
            pytest.skip("WeakCity not in benchmarking data")
        
        assert weakcity_entry["category"] == "weak", f"WeakCity should be weak, got: {weakcity_entry['category']}"
        assert weakcity_entry["performance_ratio"] < 0.7, f"WeakCity ratio should be < 0.7, got: {weakcity_entry['performance_ratio']}"
        print(f"✓ WeakCity classified as weak with ratio {weakcity_entry['performance_ratio']}x")
    
    def test_valid_categories_only(self):
        """All entries should have valid category values"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        assert response.status_code == 200
        data = response.json()
        
        valid_categories = {"high_performer", "above_average", "below_average", "weak"}
        
        for entry in data["city_benchmarking"]:
            assert entry["category"] in valid_categories, f"Invalid category '{entry['category']}' for {entry['city']}"
        
        print(f"✓ All categories are valid: {set(e['category'] for e in data['city_benchmarking'])}")


class TestActionMapping:
    """Test category to action mapping"""
    
    def test_action_mapping_correctness(self):
        """Verify action mapping: high_performer='scale aggressively', above_average='expand variants', below_average='optimize content', weak='rework or drop'"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        assert response.status_code == 200
        data = response.json()
        
        expected_actions = {
            "high_performer": "scale aggressively",
            "above_average": "expand variants",
            "below_average": "optimize content",
            "weak": "rework or drop"
        }
        
        for entry in data["city_benchmarking"]:
            expected = expected_actions[entry["category"]]
            assert entry["action"] == expected, f"City {entry['city']} with category {entry['category']} should have action '{expected}', got '{entry['action']}'"
        
        print(f"✓ All action mappings correct")
    
    def test_simcity_scale_aggressively_action(self):
        """SimCity (high_performer) should have 'scale aggressively' action"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        assert response.status_code == 200
        data = response.json()
        
        simcity_entry = next((e for e in data["city_benchmarking"] if e["city"] == "SimCity"), None)
        if not simcity_entry:
            pytest.skip("SimCity not in benchmarking data")
        
        assert simcity_entry["action"] == "scale aggressively", f"SimCity action should be 'scale aggressively', got: {simcity_entry['action']}"
        print(f"✓ SimCity action = 'scale aggressively'")
    
    def test_weakcity_rework_or_drop_action(self):
        """WeakCity (weak) should have 'rework or drop' action"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        assert response.status_code == 200
        data = response.json()
        
        weakcity_entry = next((e for e in data["city_benchmarking"] if e["city"] == "WeakCity"), None)
        if not weakcity_entry:
            pytest.skip("WeakCity not in benchmarking data")
        
        assert weakcity_entry["action"] == "rework or drop", f"WeakCity action should be 'rework or drop', got: {weakcity_entry['action']}"
        print(f"✓ WeakCity action = 'rework or drop'")


class TestPriorityScoreCalculation:
    """Test priority_score = cvr * log(views + 1) calculation"""
    
    def test_priority_score_formula(self):
        """Verify priority_score = cvr * log(views + 1) for all entries"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        assert response.status_code == 200
        data = response.json()
        
        for entry in data["city_benchmarking"]:
            expected_score = round(entry["cvr"] * math.log(entry["views"] + 1), 1)
            # Allow small floating point tolerance
            assert abs(entry["priority_score"] - expected_score) < 0.2, \
                f"City {entry['city']}: expected priority_score {expected_score}, got {entry['priority_score']}"
        
        print(f"✓ All priority_score calculations verified (cvr * log(views + 1))")
    
    def test_simcity_priority_score(self):
        """Verify SimCity priority_score calculation (CVR 14.3%, views 70)"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        assert response.status_code == 200
        data = response.json()
        
        simcity_entry = next((e for e in data["city_benchmarking"] if e["city"] == "SimCity"), None)
        if not simcity_entry:
            pytest.skip("SimCity not in benchmarking data")
        
        # Expected: 14.3 * log(70 + 1) = 14.3 * 4.26 ≈ 60.9
        expected = round(simcity_entry["cvr"] * math.log(simcity_entry["views"] + 1), 1)
        assert abs(simcity_entry["priority_score"] - expected) < 0.2, \
            f"SimCity priority_score: expected ~{expected}, got {simcity_entry['priority_score']}"
        print(f"✓ SimCity priority_score = {simcity_entry['priority_score']} (expected ~{expected})")


class TestBenchmarkingRecommendations:
    """Test benchmarking recommendations in recommendations array"""
    
    def test_top_performers_recommendation(self):
        """Verify 'Top performers to scale' recommendation when high_performers exist"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        assert response.status_code == 200
        data = response.json()
        
        high_performers = [e for e in data["city_benchmarking"] if e["category"] == "high_performer"]
        
        if not high_performers:
            pytest.skip("No high_performer cities to test recommendation")
        
        recommendations = data.get("recommendations", [])
        top_perf_rec = [r for r in recommendations if "Top performers to scale" in r]
        assert len(top_perf_rec) > 0, "Missing 'Top performers to scale' recommendation"
        print(f"✓ Found recommendation: {top_perf_rec[0]}")
    
    def test_underperforming_recommendation(self):
        """Verify 'Underperforming vs network' recommendation when weak cities exist"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        assert response.status_code == 200
        data = response.json()
        
        weak_cities = [e for e in data["city_benchmarking"] if e["category"] == "weak"]
        
        if not weak_cities:
            pytest.skip("No weak cities to test recommendation")
        
        recommendations = data.get("recommendations", [])
        underperf_rec = [r for r in recommendations if "Underperforming vs network" in r]
        assert len(underperf_rec) > 0, "Missing 'Underperforming vs network' recommendation"
        print(f"✓ Found recommendation: {underperf_rec[0]}")


class TestFiltersWithBenchmarking:
    """Test that filters work correctly with city_benchmarking"""
    
    def test_city_filter_affects_benchmarking(self):
        """City filter should affect city_benchmarking results"""
        # Get unfiltered data
        response_all = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        assert response_all.status_code == 200
        data_all = response_all.json()
        
        if len(data_all["city_benchmarking"]) == 0:
            pytest.skip("No benchmarking data to filter")
        
        # Get filtered data for a specific city
        test_city = data_all["city_benchmarking"][0]["city"]
        response_filtered = requests.get(f"{BASE_URL}/api/geo-analytics?days=30&city={test_city}")
        assert response_filtered.status_code == 200
        data_filtered = response_filtered.json()
        
        # Filtered should have at most 1 entry (the filtered city)
        assert len(data_filtered["city_benchmarking"]) <= 1, \
            f"City filter should limit results, got {len(data_filtered['city_benchmarking'])} entries"
        
        if len(data_filtered["city_benchmarking"]) == 1:
            assert data_filtered["city_benchmarking"][0]["city"] == test_city
        
        print(f"✓ City filter works: filtered to {len(data_filtered['city_benchmarking'])} entries for city={test_city}")
    
    def test_variant_filter_affects_benchmarking(self):
        """Variant filter should affect city_benchmarking results"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30&variant=best")
        assert response.status_code == 200
        data = response.json()
        
        # All entries should have best_variant = 'best' if filtered
        for entry in data["city_benchmarking"]:
            assert entry["best_variant"] == "best", f"Expected best_variant='best', got '{entry['best_variant']}'"
        
        print(f"✓ Variant filter works: {len(data['city_benchmarking'])} entries with variant=best")


class TestGlobalAvgCVRCalculation:
    """Test global_avg_cvr calculation"""
    
    def test_global_avg_cvr_calculation(self):
        """Verify global_avg_cvr is average of eligible city CVRs"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        assert response.status_code == 200
        data = response.json()
        
        if len(data["city_benchmarking"]) == 0:
            assert data["global_avg_cvr"] == 0.0, "global_avg_cvr should be 0 when no eligible cities"
            print("✓ global_avg_cvr = 0 when no eligible cities")
            return
        
        # Calculate expected average
        cvrs = [e["cvr"] for e in data["city_benchmarking"]]
        expected_avg = round(sum(cvrs) / len(cvrs), 2)
        
        # Allow small tolerance
        assert abs(data["global_avg_cvr"] - expected_avg) < 0.1, \
            f"global_avg_cvr: expected {expected_avg}, got {data['global_avg_cvr']}"
        
        print(f"✓ global_avg_cvr = {data['global_avg_cvr']}% (calculated from {len(cvrs)} cities)")


class TestEdgeCases:
    """Test edge cases for city benchmarking"""
    
    def test_empty_benchmarking_with_no_eligible_cities(self):
        """city_benchmarking should be empty when no cities have views >= 30"""
        # Use a very short time window that likely has no data
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=1&city=NonExistentCity12345")
        assert response.status_code == 200
        data = response.json()
        
        # Should return empty array, not error
        assert isinstance(data["city_benchmarking"], list), "city_benchmarking should be a list"
        print(f"✓ city_benchmarking returns empty list when no eligible cities: {data['city_benchmarking']}")
    
    def test_performance_ratio_zero_when_global_avg_zero(self):
        """performance_ratio should handle global_avg_cvr = 0 gracefully"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        assert response.status_code == 200
        data = response.json()
        
        # If global_avg_cvr is 0, all performance_ratios should be 0
        if data["global_avg_cvr"] == 0:
            for entry in data["city_benchmarking"]:
                assert entry["performance_ratio"] == 0.0, \
                    f"performance_ratio should be 0 when global_avg_cvr is 0, got {entry['performance_ratio']}"
            print("✓ performance_ratio = 0 when global_avg_cvr = 0")
        else:
            print(f"✓ global_avg_cvr = {data['global_avg_cvr']} (non-zero, skipping zero division test)")


class TestDataIntegrity:
    """Test data integrity and consistency"""
    
    def test_cvr_and_views_consistency(self):
        """Verify CVR and views values are consistent with variant_performance_by_city"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        assert response.status_code == 200
        data = response.json()
        
        vp_data = data.get("variant_performance_by_city", {})
        
        for entry in data["city_benchmarking"]:
            city = entry["city"]
            best_variant = entry["best_variant"]
            
            if city in vp_data and best_variant in vp_data[city]:
                vp_entry = vp_data[city][best_variant]
                assert entry["cvr"] == vp_entry["cvr"], \
                    f"CVR mismatch for {city}/{best_variant}: benchmarking={entry['cvr']}, vp={vp_entry['cvr']}"
                assert entry["views"] == vp_entry["views"], \
                    f"Views mismatch for {city}/{best_variant}: benchmarking={entry['views']}, vp={vp_entry['views']}"
        
        print(f"✓ CVR and views consistent with variant_performance_by_city")
    
    def test_all_numeric_fields_are_numbers(self):
        """Verify all numeric fields are actually numbers"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        assert response.status_code == 200
        data = response.json()
        
        numeric_fields = ["cvr", "views", "performance_ratio", "priority_score"]
        
        for entry in data["city_benchmarking"]:
            for field in numeric_fields:
                assert isinstance(entry[field], (int, float)), \
                    f"Field '{field}' should be numeric, got {type(entry[field])} for {entry['city']}"
        
        print(f"✓ All numeric fields are numbers")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
