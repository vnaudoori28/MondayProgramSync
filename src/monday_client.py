import os
import requests

MONDAY_API_URL = "https://api.monday.com/v2"


def _headers():
    token = os.environ.get("MONDAY_API_TOKEN")
    if not token:
        raise EnvironmentError("MONDAY_API_TOKEN not set in environment")
    return {"Authorization": token, "Content-Type": "application/json", "API-Version": "2024-01"}


def query(gql: str, variables: dict = None) -> dict:
    payload = {"query": gql}
    if variables:
        payload["variables"] = variables
    response = requests.post(MONDAY_API_URL, json=payload, headers=_headers())
    response.raise_for_status()
    data = response.json()
    if "errors" in data:
        raise RuntimeError(f"Monday API error: {data['errors']}")
    return data["data"]


def get_board_items(board_id: str) -> list:
    """Fetch all items from a board with their column values."""
    gql = """
    query ($board_id: ID!) {
      boards(ids: [$board_id]) {
        items_page(limit: 500) {
          items {
            id
            name
            group { id title }
            column_values { id text value type }
          }
        }
      }
    }
    """
    data = query(gql, {"board_id": board_id})
    return data["boards"][0]["items_page"]["items"]


def get_board_columns(board_id: str) -> list:
    """Fetch column definitions for a board."""
    gql = """
    query ($board_id: ID!) {
      boards(ids: [$board_id]) {
        columns { id title type }
      }
    }
    """
    data = query(gql, {"board_id": board_id})
    return data["boards"][0]["columns"]


def get_board_groups(board_id: str) -> list:
    """Fetch all groups in a board."""
    gql = """
    query ($board_id: ID!) {
      boards(ids: [$board_id]) {
        groups { id title }
      }
    }
    """
    data = query(gql, {"board_id": board_id})
    return data["boards"][0]["groups"]


def create_item(board_id: str, group_id: str, item_name: str, column_values: dict = None) -> str:
    """Create an item in a board group. Returns the new item's ID."""
    gql = """
    mutation ($board_id: ID!, $group_id: String!, $item_name: String!, $column_values: JSON) {
      create_item(
        board_id: $board_id
        group_id: $group_id
        item_name: $item_name
        column_values: $column_values
      ) { id }
    }
    """
    import json
    data = query(gql, {
        "board_id": board_id,
        "group_id": group_id,
        "item_name": item_name,
        "column_values": json.dumps(column_values) if column_values else "{}"
    })
    return data["create_item"]["id"]


def create_subitem(parent_item_id: str, subitem_name: str) -> tuple[str, str]:
    """Create a sub-item under a parent item. Returns (subitem_id, subitem_board_id)."""
    gql = """
    mutation ($parent_item_id: ID!, $item_name: String!) {
      create_subitem(
        parent_item_id: $parent_item_id
        item_name: $item_name
      ) { id board { id } }
    }
    """
    data = query(gql, {
        "parent_item_id": parent_item_id,
        "item_name": subitem_name,
    })
    subitem = data["create_subitem"]
    return subitem["id"], subitem["board"]["id"]


def get_subitems(parent_item_id: str) -> list:
    """Fetch all sub-items for a given parent item, including their board ID."""
    gql = """
    query ($item_id: ID!) {
      items(ids: [$item_id]) {
        subitems {
          id
          name
          board { id }
          column_values { id text value }
        }
      }
    }
    """
    data = query(gql, {"item_id": parent_item_id})
    items = data.get("items", [])
    if not items:
        return []
    return items[0].get("subitems", [])


def assign_person_to_item(item_id: str, board_id: str, user_id: str):
    """Assign a person to an item using the correct mutation for people columns."""
    gql = """
    mutation ($item_id: ID!, $board_id: ID!, $user_id: String!) {
      change_column_value(
        item_id: $item_id
        board_id: $board_id
        column_id: "person"
        value: $user_id
      ) { id }
    }
    """
    import json
    user_value = json.dumps({"personsAndTeams": [{"id": int(user_id), "kind": "person"}]})
    data = query(gql, {
        "item_id": item_id,
        "board_id": board_id,
        "user_id": user_value
    })
    return data["change_column_value"]["id"]


def item_exists(item_id: str) -> bool | None:
    """
    Check if an item exists and is active in Monday.
    Returns True if active, False if confirmed gone, None if check failed (API error etc).
    """
    gql = """
    query ($item_id: ID!) {
      items(ids: [$item_id]) {
        id
        state
      }
    }
    """
    try:
        data = query(gql, {"item_id": item_id})
        items = data.get("items", [])
        if not items:
            return False  # confirmed not found
        return items[0].get("state", "") == "active"
    except Exception as e:
        print(f"  [warn] Could not verify item {item_id}: {e}")
        return None  # unknown — don't reset


def update_item_column_values(item_id: str, column_values: dict, board_id: str = None) -> str:
    """Update column values on an existing item or sub-item."""
    import json
    gql = """
    mutation ($item_id: ID!, $board_id: ID!, $column_values: JSON!) {
      change_multiple_column_values(
        item_id: $item_id
        board_id: $board_id
        column_values: $column_values
      ) { id }
    }
    """
    data = query(gql, {
        "item_id": item_id,
        "board_id": board_id or os.environ.get("SPRINT_BOARD_ID"),
        "column_values": json.dumps(column_values)
    })
    return data["change_multiple_column_values"]["id"]


def get_users(name_filter: str = None) -> list:
    """Fetch users from the account, optionally filtered by name."""
    gql = """
    query {
      users { id name email }
    }
    """
    data = query(gql)
    users = data["users"]
    if name_filter:
        name_lower = name_filter.lower()
        users = [u for u in users if name_lower in u["name"].lower()]
    return users
