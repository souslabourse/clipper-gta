"""Publication via l'API GraphQL de Buffer (TikTok + YouTube Shorts, publics, sans audit)."""
import requests

API = "https://api.buffer.com"

CREATE = """mutation($input: CreatePostInput!) { createPost(input: $input) {
  ... on PostActionSuccess { post { id status } }
  ... on MutationError { message } } }"""


def _call(key, query, variables=None):
    r = requests.post(API, json={"query": query, "variables": variables or {}}, timeout=60,
                      headers={"Authorization": f"Bearer {key}"})
    r.raise_for_status()
    body = r.json()
    if body.get("errors"):
        raise RuntimeError(f"Buffer : {body['errors']}")
    return body["data"]


def channels(key):
    orgs = _call(key, "{ account { organizations { id name } } }")["account"]["organizations"]
    out = []
    for o in orgs:
        q = 'query($id: OrganizationId!) { channels(input: {organizationId: $id}) { id name service } }'
        out += _call(key, q, {"id": o["id"]})["channels"]
    return out


def post(key, channel_id, service, video_url, meta, category):
    data = {"channelId": channel_id, "schedulingType": "automatic", "mode": "shareNow",
            "text": meta["description"], "assets": [{"video": {"url": video_url}}]}
    if service == "youtube":
        data["metadata"] = {"youtube": {"title": meta["title"][:100], "categoryId": category,
                                        "privacy": "public", "madeForKids": False}}
    res = _call(key, CREATE, {"input": data})["createPost"]
    if "message" in res:
        raise RuntimeError(f"Buffer refuse le post : {res['message']}")
    return res["post"]["id"]
