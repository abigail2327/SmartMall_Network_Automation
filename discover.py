import requests
from config import GNS3_URL as GNS3_HOST, GNS3_AUTH, PROJECT_NAME
import json


def get_project_id():
    r = requests.get(f"{GNS3_HOST}/v2/projects", auth=GNS3_AUTH)
    projects = r.json()
    for p in projects:
        if p["name"] == PROJECT_NAME:
            return p["project_id"]
    raise Exception(f"Project '{PROJECT_NAME}' not found")

def get_nodes(project_id):
    r = requests.get(f"{GNS3_HOST}/v2/projects/{project_id}/nodes", auth=GNS3_AUTH)
    nodes = []
    for n in r.json():
        nodes.append({
            "id": n["node_id"],
            "name": n["name"],
            "type": n["node_type"],
            "console_port": n.get("console"),
            "console_host": n.get("console_host", GNS3_HOST),
            "interfaces": [p["name"] for p in n.get("ports", [])]
        })
    return nodes

def get_links(project_id, nodes):
    r = requests.get(f"{GNS3_HOST}/v2/projects/{project_id}/links", auth=GNS3_AUTH)
    id_to_name = {n["id"]: n["name"] for n in nodes}
    links = []
    for l in r.json():
        endpoints = l.get("nodes", [])
        if len(endpoints) == 2:
            links.append({
                "device_a": id_to_name.get(endpoints[0]["node_id"], "unknown"),
                "interface_a": endpoints[0].get("label", {}).get("text", ""),
                "device_b": id_to_name.get(endpoints[1]["node_id"], "unknown"),
                "interface_b": endpoints[1].get("label", {}).get("text", "")
            })
    return links

def discover():
    print("Connecting to GNS3...")
    project_id = get_project_id()
    print(f"Found project: {PROJECT_NAME} ({project_id})")
    
    nodes = get_nodes(project_id)
    print(f"Found {len(nodes)} devices")
    
    links = get_links(project_id, nodes)
    print(f"Found {len(links)} links")
    
    topology = {
        "project": PROJECT_NAME,
        "gns3_host": GNS3_HOST,
        "nodes": nodes,
        "links": links
    }
    
    with open("topology.json", "w") as f:
        json.dump(topology, f, indent=2)
    
    print("topology.json saved!")
    return topology

if __name__ == "__main__":
    discover()
