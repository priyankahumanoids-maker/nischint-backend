import requests
import sys
from datetime import datetime
import json

class NischintAPITester:
    def __init__(self, base_url="https://gps-mic-restart.preview.emergentagent.com"):
        self.base_url = base_url
        self.tests_run = 0
        self.tests_passed = 0
        self.test_results = []

    def run_test(self, name, method, endpoint, expected_status, data=None, description=""):
        """Run a single API test"""
        url = f"{self.base_url}/{endpoint}"
        headers = {'Content-Type': 'application/json'}

        self.tests_run += 1
        print(f"\n🔍 Testing {name}...")
        print(f"   URL: {url}")
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=headers, timeout=10)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=headers, timeout=10)

            success = response.status_code == expected_status
            
            result = {
                "test_name": name,
                "method": method,
                "endpoint": endpoint,
                "expected_status": expected_status,
                "actual_status": response.status_code,
                "success": success,
                "description": description,
                "response_preview": ""
            }
            
            if success:
                self.tests_passed += 1
                print(f"✅ Passed - Status: {response.status_code}")
                try:
                    response_data = response.json()
                    result["response_preview"] = str(response_data)[:200]
                    print(f"   Response: {response_data}")
                except:
                    result["response_preview"] = response.text[:200]
                    print(f"   Response: {response.text[:200]}")
            else:
                print(f"❌ Failed - Expected {expected_status}, got {response.status_code}")
                print(f"   Response: {response.text[:300]}")
                result["response_preview"] = response.text[:300]

            self.test_results.append(result)
            return success, response.json() if success else {}

        except requests.exceptions.Timeout:
            print(f"❌ Failed - Request timeout")
            result = {
                "test_name": name,
                "method": method,
                "endpoint": endpoint,
                "expected_status": expected_status,
                "actual_status": "TIMEOUT",
                "success": False,
                "description": description,
                "response_preview": "Request timeout"
            }
            self.test_results.append(result)
            return False, {}
        except Exception as e:
            print(f"❌ Failed - Error: {str(e)}")
            result = {
                "test_name": name,
                "method": method,
                "endpoint": endpoint,
                "expected_status": expected_status,
                "actual_status": "ERROR",
                "success": False,
                "description": description,
                "response_preview": f"Error: {str(e)}"
            }
            self.test_results.append(result)
            return False, {}

    def test_health_check(self):
        """Test the main API health endpoint"""
        return self.run_test(
            "API Health Check",
            "GET",
            "api/",
            200,
            description="Basic API health check endpoint"
        )

    def test_create_status_check(self):
        """Test creating a status check"""
        test_data = {
            "client_name": f"test_client_{datetime.now().strftime('%H%M%S')}"
        }
        
        return self.run_test(
            "Create Status Check",
            "POST",
            "api/status",
            200,
            data=test_data,
            description="Test creating a new status check entry"
        )

    def test_get_status_checks(self):
        """Test retrieving status checks"""
        return self.run_test(
            "Get Status Checks",
            "GET",
            "api/status",
            200,
            description="Test retrieving all status checks"
        )

    def print_summary(self):
        """Print test summary"""
        print(f"\n{'='*60}")
        print(f"📊 NISCHINT API Test Results")
        print(f"{'='*60}")
        print(f"Tests passed: {self.tests_passed}/{self.tests_run}")
        
        success_rate = (self.tests_passed / self.tests_run * 100) if self.tests_run > 0 else 0
        print(f"Success rate: {success_rate:.1f}%")
        
        if self.tests_passed == self.tests_run:
            print("✅ All tests passed!")
            return True
        else:
            print("❌ Some tests failed!")
            print(f"\nFailed tests:")
            for result in self.test_results:
                if not result["success"]:
                    print(f"  - {result['test_name']}: {result['actual_status']}")
            return False

def main():
    """Main test execution function"""
    print("🚀 Starting NISCHINT API Testing...")
    print(f"⏰ Test started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    tester = NischintAPITester()
    
    # Run tests in logical order
    print("\n" + "="*60)
    print("Phase 1: Basic Health Check")
    print("="*60)
    
    health_success, _ = tester.test_health_check()
    
    if health_success:
        print("\n" + "="*60)
        print("Phase 2: Status Check Operations")
        print("="*60)
        
        tester.test_create_status_check()
        tester.test_get_status_checks()
    else:
        print("\n⚠️  Skipping further tests due to health check failure")
    
    # Print final summary
    all_passed = tester.print_summary()
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())