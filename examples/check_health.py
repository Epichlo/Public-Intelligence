"""Example script to check the health status of a running Node."""

import httpx


def main() -> None:
    """Send a request to the Node's health endpoint and print the status."""
    url = "http://localhost:8000/health"
    try:
        response = httpx.get(url)
        print(f"Response Status Code: {response.status_code}")
        print(f"Response Body: {response.json()}")
    except httpx.RequestError as e:
        print(f"Failed to connect to Node at {url}: {e}")


if __name__ == "__main__":
    main()
