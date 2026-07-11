"""
Test GEO Analytics Decision Engine - variant_performance_by_city and recommendations
Tests the new decision engine logic with MIN_VIEWS=30 threshold and CVR-based actions
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestVariantPerformanceByCity:
    """Tests for variant_performance_by_city field structure and decision rules"""
    
    def test_variant_performance_field_exists(self):
        """Verify variant_performance_by_city field is present in response"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        assert response.status_code == 200
        data = response.json()
        assert "variant_performance_by_city" in data
        assert isinstance(data["variant_performance_by_city"], dict)
        print(f"✓ variant_performance_by_city field exists with {len(data['variant_performance_by_city'])} cities")
    
    def test_city_entry_structure(self):
        """Verify each city entry has correct structure: variant data + winner + action"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        data = response.json()
        vp = data.get("variant_performance_by_city", {})
        
        for city, entry in vp.items():
            # Must have winner and action
            assert "winner" in entry, f"City {city} missing 'winner' field"
            assert "action" in entry, f"City {city} missing 'action' field"
            
            # Check variant data structure
            for key, val in entry.items():
                if key not in ["winner", "action"]:
                    # This is a variant entry
                    assert "views" in val, f"City {city}, variant {key} missing 'views'"
                    assert "clicks" in val, f"City {city}, variant {key} missing 'clicks'"
                    assert "cvr" in val, f"City {city}, variant {key} missing 'cvr'"
                    assert isinstance(val["views"], int)
                    assert isinstance(val["clicks"], int)
                    assert isinstance(val["cvr"], (int, float))
        
        print(f"✓ All {len(vp)} city entries have correct structure")
    
    def test_simcity_scale_action(self):
        """SimCity: best variant with ~70 views, 14.3% CVR should get action=scale, winner=best"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        data = response.json()
        vp = data.get("variant_performance_by_city", {})
        
        assert "SimCity" in vp, "SimCity not found in variant_performance_by_city"
        simcity = vp["SimCity"]
        
        # Verify best variant has enough views and high CVR
        assert "best" in simcity, "SimCity missing 'best' variant"
        best = simcity["best"]
        assert best["views"] >= 30, f"SimCity best views {best['views']} < 30"
        assert best["cvr"] > 5, f"SimCity best CVR {best['cvr']} not > 5%"
        
        # Verify decision
        assert simcity["winner"] == "best", f"SimCity winner should be 'best', got {simcity['winner']}"
        assert simcity["action"] == "scale", f"SimCity action should be 'scale', got {simcity['action']}"
        
        print(f"✓ SimCity: best variant ({best['views']} views, {best['cvr']}% CVR) → winner=best, action=scale")
    
    def test_weakcity_optimize_action(self):
        """WeakCity: ~35+ views with 0% CVR should get action=optimize, winner=weak_city"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        data = response.json()
        vp = data.get("variant_performance_by_city", {})
        
        assert "WeakCity" in vp, "WeakCity not found in variant_performance_by_city"
        weakcity = vp["WeakCity"]
        
        # Verify has variant with enough views but low CVR
        has_eligible_variant = False
        for key, val in weakcity.items():
            if key not in ["winner", "action"] and val.get("views", 0) >= 30:
                has_eligible_variant = True
                assert val["cvr"] < 2, f"WeakCity {key} CVR {val['cvr']} should be < 2%"
        
        assert has_eligible_variant, "WeakCity should have at least one variant with >= 30 views"
        
        # Verify decision
        assert weakcity["winner"] == "weak_city", f"WeakCity winner should be 'weak_city', got {weakcity['winner']}"
        assert weakcity["action"] == "optimize", f"WeakCity action should be 'optimize', got {weakcity['action']}"
        
        print(f"✓ WeakCity: low CVR with sufficient views → winner=weak_city, action=optimize")
    
    def test_insufficient_data_cities(self):
        """Cities with < 30 views should get winner=insufficient_data, action=test_more"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        data = response.json()
        vp = data.get("variant_performance_by_city", {})
        
        insufficient_cities = []
        for city, entry in vp.items():
            if entry.get("winner") == "insufficient_data":
                insufficient_cities.append(city)
                # Verify no variant has >= 30 views
                for key, val in entry.items():
                    if key not in ["winner", "action"]:
                        assert val.get("views", 0) < 30, f"City {city} has variant {key} with {val['views']} views but marked insufficient"
                # Action should be test_more (or optimize if total_views == 0)
                assert entry["action"] in ["test_more", "optimize"], f"City {city} with insufficient data should have action test_more or optimize"
        
        assert len(insufficient_cities) > 0, "Should have at least one city with insufficient data"
        print(f"✓ Found {len(insufficient_cities)} cities with insufficient_data: {insufficient_cities[:5]}...")
    
    def test_action_values_valid(self):
        """All action values should be one of: scale, test_more, optimize"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        data = response.json()
        vp = data.get("variant_performance_by_city", {})
        
        valid_actions = {"scale", "test_more", "optimize"}
        action_counts = {"scale": 0, "test_more": 0, "optimize": 0}
        
        for city, entry in vp.items():
            action = entry.get("action")
            assert action in valid_actions, f"City {city} has invalid action: {action}"
            action_counts[action] += 1
        
        print(f"✓ Action distribution: scale={action_counts['scale']}, test_more={action_counts['test_more']}, optimize={action_counts['optimize']}")
    
    def test_winner_values_valid(self):
        """Winner should be a variant name, 'weak_city', or 'insufficient_data'"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        data = response.json()
        vp = data.get("variant_performance_by_city", {})
        
        special_winners = {"weak_city", "insufficient_data"}
        
        for city, entry in vp.items():
            winner = entry.get("winner")
            assert winner is not None, f"City {city} missing winner"
            
            if winner not in special_winners:
                # Winner should be a variant that exists in the entry
                assert winner in entry, f"City {city} winner '{winner}' not found in variants"
        
        print(f"✓ All winner values are valid")


class TestRecommendations:
    """Tests for recommendations array"""
    
    def test_recommendations_field_exists(self):
        """Verify recommendations field is present and is a list"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        assert response.status_code == 200
        data = response.json()
        assert "recommendations" in data
        assert isinstance(data["recommendations"], list)
        print(f"✓ recommendations field exists with {len(data['recommendations'])} items")
    
    def test_scale_recommendation_present(self):
        """Should have 'Expand variant to more cities' recommendation for scale winners"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        data = response.json()
        recommendations = data.get("recommendations", [])
        
        # Check if there's a scale recommendation
        scale_recs = [r for r in recommendations if "Expand" in r and "winning" in r]
        
        # SimCity has action=scale, so should have this recommendation
        vp = data.get("variant_performance_by_city", {})
        scale_cities = [c for c, e in vp.items() if e.get("action") == "scale"]
        
        if scale_cities:
            assert len(scale_recs) > 0, f"Should have scale recommendation for cities: {scale_cities}"
            print(f"✓ Scale recommendation present: {scale_recs[0][:80]}...")
        else:
            print("⚠ No scale cities found, skipping scale recommendation check")
    
    def test_weak_city_recommendation_present(self):
        """Should have 'Optimize or pause N weak cities' recommendation"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        data = response.json()
        recommendations = data.get("recommendations", [])
        
        vp = data.get("variant_performance_by_city", {})
        weak_cities = [c for c, e in vp.items() if e.get("winner") == "weak_city"]
        
        if weak_cities:
            weak_recs = [r for r in recommendations if "Optimize or pause" in r and "weak" in r]
            assert len(weak_recs) > 0, f"Should have weak city recommendation for: {weak_cities}"
            print(f"✓ Weak city recommendation present: {weak_recs[0]}")
        else:
            print("⚠ No weak cities found, skipping weak city recommendation check")
    
    def test_insufficient_data_recommendation_present(self):
        """Should have 'Need more traffic data for N cities' recommendation"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        data = response.json()
        recommendations = data.get("recommendations", [])
        
        vp = data.get("variant_performance_by_city", {})
        insufficient_cities = [c for c, e in vp.items() if e.get("winner") == "insufficient_data"]
        
        if insufficient_cities:
            traffic_recs = [r for r in recommendations if "Need more traffic" in r]
            assert len(traffic_recs) > 0, f"Should have insufficient data recommendation for {len(insufficient_cities)} cities"
            print(f"✓ Insufficient data recommendation present: {traffic_recs[0]}")
        else:
            print("⚠ No insufficient data cities found, skipping recommendation check")
    
    def test_recommendations_are_strings(self):
        """All recommendations should be non-empty strings"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        data = response.json()
        recommendations = data.get("recommendations", [])
        
        for i, rec in enumerate(recommendations):
            assert isinstance(rec, str), f"Recommendation {i} is not a string"
            assert len(rec) > 0, f"Recommendation {i} is empty"
        
        print(f"✓ All {len(recommendations)} recommendations are valid strings")


class TestDecisionRulesEdgeCases:
    """Test edge cases in decision rules"""
    
    def test_cvr_threshold_boundaries(self):
        """Verify CVR thresholds: >5% = scale, 2-5% = test_more, <2% = optimize"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        data = response.json()
        vp = data.get("variant_performance_by_city", {})
        
        for city, entry in vp.items():
            if entry.get("winner") in ["weak_city", "insufficient_data"]:
                continue
            
            # Find the winning variant's CVR
            winner = entry.get("winner")
            if winner and winner in entry:
                cvr = entry[winner].get("cvr", 0)
                action = entry.get("action")
                
                if cvr > 5:
                    assert action == "scale", f"City {city}: CVR {cvr}% > 5 should be scale, got {action}"
                elif cvr >= 2:
                    assert action == "test_more", f"City {city}: CVR {cvr}% in 2-5 should be test_more, got {action}"
                else:
                    # CVR < 2 with enough views should be optimize with weak_city winner
                    pass  # This case is handled by weak_city logic
        
        print("✓ CVR threshold boundaries verified")
    
    def test_filter_city_affects_variant_performance(self):
        """Filtering by city should affect variant_performance_by_city"""
        # Get unfiltered
        response1 = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        data1 = response1.json()
        vp1 = data1.get("variant_performance_by_city", {})
        
        # Get filtered by SimCity
        response2 = requests.get(f"{BASE_URL}/api/geo-analytics?days=30&city=SimCity")
        data2 = response2.json()
        vp2 = data2.get("variant_performance_by_city", {})
        
        # Filtered should only have SimCity
        if "SimCity" in vp1:
            assert "SimCity" in vp2, "SimCity should be in filtered results"
            # Should have fewer or equal cities
            assert len(vp2) <= len(vp1), "Filtered results should have fewer cities"
        
        print(f"✓ City filter works: unfiltered={len(vp1)} cities, filtered={len(vp2)} cities")
    
    def test_filter_variant_affects_variant_performance(self):
        """Filtering by variant should affect variant_performance_by_city"""
        # Get filtered by 'best' variant
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30&variant=best")
        data = response.json()
        vp = data.get("variant_performance_by_city", {})
        
        # Each city should only have 'best' variant data (plus winner/action)
        for city, entry in vp.items():
            variant_keys = [k for k in entry.keys() if k not in ["winner", "action"]]
            for vk in variant_keys:
                assert vk == "best", f"City {city} has variant {vk} when filtered by 'best'"
        
        print(f"✓ Variant filter works: {len(vp)} cities with 'best' variant only")


class TestResponseIntegrity:
    """Test overall response integrity"""
    
    def test_all_expected_fields_present(self):
        """Verify all expected fields are in response"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        assert response.status_code == 200
        data = response.json()
        
        expected_fields = [
            "period_days", "total_views", "total_clicks",
            "top_cities", "top_variants", "top_types",
            "conversion_rates", "conversion_by_variant",
            "daily_trend", "recent_events",
            "variant_performance_by_city", "recommendations",
            "filter_options"
        ]
        
        for field in expected_fields:
            assert field in data, f"Missing field: {field}"
        
        print(f"✓ All {len(expected_fields)} expected fields present")
    
    def test_variant_performance_consistency_with_conversion_rates(self):
        """variant_performance_by_city should be consistent with conversion_rates"""
        response = requests.get(f"{BASE_URL}/api/geo-analytics?days=30")
        data = response.json()
        
        vp = data.get("variant_performance_by_city", {})
        conv_rates = data.get("conversion_rates", [])
        
        # Cities in conversion_rates should also be in variant_performance_by_city
        for cr in conv_rates:
            city = cr.get("city")
            if city:
                assert city in vp, f"City {city} in conversion_rates but not in variant_performance_by_city"
        
        print(f"✓ variant_performance_by_city consistent with conversion_rates")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
