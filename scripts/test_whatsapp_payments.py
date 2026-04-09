#!/usr/bin/env python3
"""
WhatsApp Payments Integration Test Script

Run this script to verify your WhatsApp Payments configuration.
"""
import os
import sys
import json
from typing import Dict, List

try:
    import httpx
    from dotenv import load_dotenv
except ImportError:
    print("❌ Required packages not installed.")
    print("Run: pip install httpx python-dotenv")
    sys.exit(1)


# ANSI colors for terminal output
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'


def print_success(msg: str):
    print(f"{Colors.GREEN}✅ {msg}{Colors.END}")


def print_error(msg: str):
    print(f"{Colors.RED}❌ {msg}{Colors.END}")


def print_warning(msg: str):
    print(f"{Colors.YELLOW}⚠️  {msg}{Colors.END}")


def print_info(msg: str):
    print(f"{Colors.BLUE}ℹ️  {msg}{Colors.END}")


def print_header(msg: str):
    print(f"\n{Colors.BOLD}{msg}{Colors.END}")
    print("=" * 50)


def load_env():
    """Load environment variables from .env file"""
    load_dotenv()
    print_info("Loaded environment variables from .env")


def check_env_vars() -> Dict[str, str]:
    """Check if required environment variables are set"""
    print_header("Checking Environment Variables")

    required_vars = {
        "WHATSAPP_PHONE_ID": "Required for sending messages",
        "WHATSAPP_ACCESS_TOKEN": "Required for API authentication",
        "WHATSAPP_WABA_ID": "Required for Payments on WhatsApp",
        "WHATSAPP_PAYMENT_CONFIG_ID": "Required for payment configuration",
        "WHATSAPP_PAYMENT_MID": "Required for Razorpay integration",
        "WHATSAPP_FLOW_ID": "Required for WhatsApp Flow",
        "SUBSCRIPTIONS_URL": "Required for subscription service"
    }

    missing = []
    present = []

    for var_name, description in required_vars.items():
        value = os.getenv(var_name)
        if value:
            # Mask sensitive values
            if "TOKEN" in var_name or "SECRET" in var_name:
                display_value = f"{value[:8]}..." if len(value) > 8 else "***"
            elif "MID" in var_name:
                display_value = f"{value[:4]}..." if len(value) > 4 else "***"
            else:
                display_value = value
            print_success(f"{var_name}: {display_value}")
            present.append(var_name)
        else:
            print_error(f"{var_name}: Not set ({description})")
            missing.append(var_name)

    return {"missing": missing, "present": present}


def test_health_endpoints(base_url: str) -> Dict:
    """Test health check endpoints"""
    print_header("Testing Health Endpoints")

    results = {}

    # Test WhatsApp service health
    print_info("Testing WhatsApp service health...")
    try:
        response = httpx.get(f"{base_url}/health", timeout=10)
        if response.status_code == 200:
            print_success(f"WhatsApp service is healthy")
            results["whatsapp_health"] = True
        else:
            print_error(f"WhatsApp service returned status {response.status_code}")
            results["whatsapp_health"] = False
    except Exception as e:
        print_error(f"Failed to connect to WhatsApp service: {e}")
        results["whatsapp_health"] = False

    # Test WhatsApp Payments configuration
    print_info("Testing WhatsApp Payments configuration...")
    try:
        response = httpx.get(f"{base_url}/health/whatsapp-payments", timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "enabled":
                print_success("WhatsApp Payments is enabled")
                results["whatsapp_payments"] = True
                results["whatsapp_payments_config"] = data
            else:
                print_warning(f"WhatsApp Payments not fully configured")
                print_warning(f"Missing: {data.get('missing_vars', [])}")
                results["whatsapp_payments"] = False
                results["whatsapp_payments_config"] = data
        else:
            print_error(f"Health check returned status {response.status_code}")
            results["whatsapp_payments"] = False
    except Exception as e:
        print_error(f"Failed to check WhatsApp Payments: {e}")
        results["whatsapp_payments"] = False

    return results


def test_subscriptions_service(subscriptions_url: str) -> Dict:
    """Test subscriptions service health"""
    print_header("Testing Subscriptions Service")

    results = {}

    # Test health endpoint
    print_info("Testing subscriptions service health...")
    try:
        response = httpx.get(f"{subscriptions_url}/health", timeout=10)
        if response.status_code == 200:
            print_success("Subscriptions service is healthy")
            results["subscriptions_health"] = True
        else:
            print_error(f"Subscriptions service returned status {response.status_code}")
            results["subscriptions_health"] = False
    except Exception as e:
        print_error(f"Failed to connect to subscriptions service: {e}")
        results["subscriptions_health"] = False

    # Test WhatsApp Payments webhook configuration
    print_info("Testing WhatsApp Payments webhook configuration...")
    try:
        response = httpx.get(f"{subscriptions_url}/health/whatsapp-payments", timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "configured":
                print_success("WhatsApp Payments webhook is configured")
                results["webhook_configured"] = True
            else:
                print_warning(f"WhatsApp Payments webhook not fully configured")
                print_warning(f"Missing: {data.get('missing_vars', [])}")
                results["webhook_configured"] = False
        else:
            print_error(f"Webhook health check returned status {response.status_code}")
            results["webhook_configured"] = False
    except Exception as e:
        print_error(f"Failed to check webhook configuration: {e}")
        results["webhook_configured"] = False

    return results


def test_flow_metadata(base_url: str, subscriptions_url: str) -> Dict:
    """Test Flow metadata endpoint"""
    print_header("Testing Flow Metadata")

    results = {}

    # Test plan list endpoint
    print_info("Testing plan list endpoint...")
    try:
        response = httpx.get(f"{subscriptions_url}/plans?active_only=true", timeout=10)
        if response.status_code == 200:
            data = response.json()
            plans = data.get("plans", [])
            print_success(f"Found {len(plans)} active plans")
            for plan in plans[:3]:  # Show first 3 plans
                print(f"  - {plan.get('name')}: ₹{plan.get('price', 0) // 100}")
            results["plans"] = plans
        else:
            print_error(f"Plans endpoint returned status {response.status_code}")
            results["plans"] = []
    except Exception as e:
        print_error(f"Failed to fetch plans: {e}")
        results["plans"] = []

    return results


def generate_summary(env_check: Dict, health_results: Dict, subscriptions_results: Dict, flow_results: Dict):
    """Generate final summary"""
    print_header("Test Summary")

    all_passed = True

    # Environment variables check
    if env_check["missing"]:
        print_warning(f"Missing {len(env_check['missing'])} environment variables")
        all_passed = False
    else:
        print_success("All required environment variables are set")

    # Health checks
    if health_results.get("whatsapp_health"):
        print_success("WhatsApp service is healthy")
    else:
        print_error("WhatsApp service is not healthy")
        all_passed = False

    if health_results.get("whatsapp_payments"):
        print_success("WhatsApp Payments is enabled")
    else:
        print_warning("WhatsApp Payments is not enabled (will use payment links)")

    # Subscriptions service
    if subscriptions_results.get("subscriptions_health"):
        print_success("Subscriptions service is healthy")
    else:
        print_error("Subscriptions service is not healthy")
        all_passed = False

    if subscriptions_results.get("webhook_configured"):
        print_success("WhatsApp Payments webhook is configured")
    else:
        print_warning("WhatsApp Payments webhook is not configured")

    # Final verdict
    print_header("Final Verdict")

    if all_passed:
        print_success("🎉 All critical tests passed! Ready for deployment.")
    else:
        print_warning("⚠️  Some tests failed. Please fix the issues above.")
        print_info("You can still deploy - system will fallback to payment links.")

    # Next steps
    if not health_results.get("whatsapp_payments"):
        print("\n📋 Next Steps:")
        print("1. Add missing environment variables in Coolify")
        print("2. Restart the service")
        print("3. Run this test script again")
        print("4. Once all pass, proceed with deployment")


def main():
    print(f"""
{Colors.BOLD}
╔══════════════════════════════════════════════════════════╗
║        WhatsApp Payments Integration Test                 ║
╚══════════════════════════════════════════════════════════╝
{Colors.END}
    """)

    # Load environment
    load_env()

    # Get URLs
    whatsapp_url = os.getenv("WHATSAPP_SERVICE_URL", "http://localhost:8003")
    subscriptions_url = os.getenv("SUBSCRIPTIONS_URL", "http://localhost:8000")

    print_info(f"WhatsApp Service URL: {whatsapp_url}")
    print_info(f"Subscriptions Service URL: {subscriptions_url}")

    # Run tests
    env_check = check_env_vars()
    health_results = test_health_endpoints(whatsapp_url)
    subscriptions_results = test_subscriptions_service(subscriptions_url)
    flow_results = test_flow_metadata(whatsapp_url, subscriptions_url)

    # Generate summary
    generate_summary(env_check, health_results, subscriptions_results, flow_results)


if __name__ == "__main__":
    main()
