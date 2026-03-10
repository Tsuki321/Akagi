"""
MajsoulMax integration for Akagi.

This package ports MajsoulMax's cosmetic-unlock functionality into Akagi's
MITM pipeline. It intercepts and modifies Majsoul WebSocket/protobuf messages
*before* Akagi's bridge parses them for AI analysis, so both cosmetic unlocking
and AI suggestions work simultaneously.

Source: https://github.com/Avenshy/MajsoulMax
"""
