"""Async client for Listmonk's REST API.

Listmonk docs: https://listmonk.app/docs/apis/
All endpoints return JSON. Auth is HTTP Basic.
"""

import logging
from typing import Any

import httpx

from ..config import settings

logger = logging.getLogger("leadgen.listmonk.client")


class ListmonkClient:
    """Async client for Listmonk REST API."""

    def __init__(
        self,
        base_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ):
        self._base_url = (base_url or settings.listmonk_url).rstrip("/")
        self._auth = (
            username or settings.listmonk_username,
            password or settings.listmonk_password,
        )

    async def _request(
        self, method: str, path: str, json: dict | None = None, params: dict | None = None,
    ) -> dict:
        url = f"{self._base_url}{path}"
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            resp = await client.request(
                method, url, json=json, params=params,
                auth=self._auth,
            )
            if resp.status_code >= 400:
                logger.error("Listmonk %s %s -> %d: %s", method, path, resp.status_code, resp.text[:200])
                return {"error": resp.text, "status": resp.status_code}
            return resp.json()

    # --- Health ---

    async def health(self) -> dict:
        """GET /api/health"""
        return await self._request("GET", "/api/health")

    # --- Subscribers ---

    async def create_subscriber(
        self, email: str, name: str,
        lists: list[int] | None = None,
        attribs: dict | None = None,
        status: str = "enabled",
    ) -> dict:
        """POST /api/subscribers"""
        payload: dict[str, Any] = {
            "email": email,
            "name": name,
            "status": status,
        }
        if lists:
            payload["lists"] = lists
        if attribs:
            payload["attribs"] = attribs
        return await self._request("POST", "/api/subscribers", json=payload)

    async def get_subscriber(self, subscriber_id: int) -> dict:
        """GET /api/subscribers/{id}"""
        return await self._request("GET", f"/api/subscribers/{subscriber_id}")

    async def query_subscribers(
        self, query: str = "", page: int = 1, per_page: int = 50,
    ) -> dict:
        """GET /api/subscribers with optional SQL query."""
        params = {"page": page, "per_page": per_page}
        if query:
            params["query"] = query
        return await self._request("GET", "/api/subscribers", params=params)

    async def add_subscriber_to_list(self, subscriber_ids: list[int], list_ids: list[int]) -> dict:
        """PUT /api/subscribers/lists"""
        return await self._request("PUT", "/api/subscribers/lists", json={
            "ids": subscriber_ids,
            "action": "add",
            "target_list_ids": list_ids,
        })

    # --- Lists ---

    async def create_list(
        self, name: str, type: str = "private", optin: str = "single",
        description: str = "",
    ) -> dict:
        """POST /api/lists"""
        return await self._request("POST", "/api/lists", json={
            "name": name,
            "type": type,
            "optin": optin,
            "description": description,
        })

    async def get_lists(self) -> dict:
        """GET /api/lists"""
        return await self._request("GET", "/api/lists")

    # --- Campaigns ---

    async def create_campaign(
        self, name: str, subject: str, body: str,
        list_ids: list[int],
        from_email: str | None = None,
        content_type: str = "richtext",
        template_id: int = 1,
    ) -> dict:
        """POST /api/campaigns"""
        payload: dict[str, Any] = {
            "name": name,
            "subject": subject,
            "body": body,
            "lists": list_ids,
            "content_type": content_type,
            "template_id": template_id,
        }
        if from_email:
            payload["from_email"] = from_email
        return await self._request("POST", "/api/campaigns", json=payload)

    async def get_campaign(self, campaign_id: int) -> dict:
        """GET /api/campaigns/{id}"""
        return await self._request("GET", f"/api/campaigns/{campaign_id}")

    async def update_campaign_status(self, campaign_id: int, status: str) -> dict:
        """PUT /api/campaigns/{id}/status

        status: 'running', 'paused', 'cancelled'
        """
        return await self._request(
            "PUT", f"/api/campaigns/{campaign_id}/status",
            json={"status": status},
        )

    async def start_campaign(self, campaign_id: int) -> dict:
        """Start a campaign."""
        return await self.update_campaign_status(campaign_id, "running")

    async def pause_campaign(self, campaign_id: int) -> dict:
        """Pause a campaign."""
        return await self.update_campaign_status(campaign_id, "paused")

    async def get_campaigns(self, page: int = 1, per_page: int = 50) -> dict:
        """GET /api/campaigns"""
        return await self._request("GET", "/api/campaigns", params={
            "page": page, "per_page": per_page,
        })

    # --- Templates ---

    async def create_template(self, name: str, body: str, type: str = "campaign") -> dict:
        """POST /api/templates"""
        return await self._request("POST", "/api/templates", json={
            "name": name,
            "body": body,
            "type": type,
        })

    async def get_templates(self) -> dict:
        """GET /api/templates"""
        return await self._request("GET", "/api/templates")

    # --- Bounces ---

    async def get_bounces(self, page: int = 1, per_page: int = 100) -> dict:
        """GET /api/bounces"""
        return await self._request("GET", "/api/bounces", params={
            "page": page, "per_page": per_page,
        })
