from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.database import get_db
from app.main import app

# Configure settings for test
settings.google_client_id = "test-google-client-id"
settings.google_client_secret = "test-google-client-secret"
settings.google_redirect_uri = "http://localhost:5173"
settings.github_client_id = "test-github-client-id"
settings.github_client_secret = "test-github-client-secret"
settings.github_redirect_uri = "http://localhost:5173"
settings.jwt_secret = "test-jwt-secret-at-least-32-characters"

# Setup database session mock
mock_db = AsyncMock()


async def override_get_db():
    yield mock_db


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def test_get_google_url():
    response = client.get("/api/auth/google/url")
    assert response.status_code == 200
    data = response.json()
    assert "url" in data
    assert "client_id=test-google-client-id" in data["url"]
    assert "redirect_uri=http://localhost:5173" in data["url"]


def test_get_github_url():
    response = client.get("/api/auth/github/url")
    assert response.status_code == 200
    data = response.json()
    assert "url" in data
    assert "client_id=test-github-client-id" in data["url"]
    assert "redirect_uri=http://localhost:5173" in data["url"]


@patch("httpx.AsyncClient.post")
@patch("httpx.AsyncClient.get")
def test_oauth_callback_google_success(mock_get, mock_post):
    # Mock token exchange response
    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    mock_post_resp.json.return_value = {"access_token": "mock-google-access-token"}
    mock_post.return_value = mock_post_resp

    # Mock user profile response
    mock_get_resp = MagicMock()
    mock_get_resp.status_code = 200
    mock_get_resp.json.return_value = {
        "email": "testuser@gmail.com",
        "sub": "google-user-sub-123",
        "name": "Test Google User",
        "picture": "http://example.com/avatar.jpg",
    }
    mock_get.return_value = mock_get_resp

    # Mock DB select to return None (new user registration)
    mock_scalar = MagicMock()
    mock_scalar.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_scalar

    # Reset mock database history
    mock_db.add.reset_mock()
    mock_db.commit.reset_mock()

    response = client.post(
        "/api/auth/callback", json={"code": "auth-code-123", "provider": "google"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "testuser@gmail.com"
    assert data["profile_data"]["fullName"] == "Test Google User"
    assert data["profile_data"]["provider"] == "google"

    # Verify user creation in DB
    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()
    assert "access_token" in response.cookies


def test_logout():
    response = client.post("/api/auth/logout")
    assert response.status_code == 200
    assert response.json() == {"status": "logged_out"}
    # Verify cookie has expired
    cookie = response.cookies.get("access_token")
    assert cookie is None or cookie == ""
