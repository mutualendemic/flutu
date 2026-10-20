import os

import dns.resolver
from flask import current_app
from pymongo import MongoClient


def _configure_missing_system_dns():
    if os.path.exists("/etc/resolv.conf"):
        return

    resolver = dns.resolver.Resolver(configure=False)
    nameservers = current_app.config.get("MONGODB_DNS_NAMESERVERS", "1.1.1.1,8.8.8.8")
    resolver.nameservers = [server.strip() for server in nameservers.split(",") if server.strip()]
    if resolver.nameservers:
        dns.resolver.default_resolver = resolver


def get_collection(name):
    uri = current_app.config.get("MONGODB_URI")
    if not uri:
        raise RuntimeError("MongoDB is not configured")

    client = current_app.extensions.get("mongodb_client")
    if client is None:
        _configure_missing_system_dns()
        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        current_app.extensions["mongodb_client"] = client

    database_name = current_app.config.get("MONGODB_DATABASE", "flutu")
    return client[database_name][name]
