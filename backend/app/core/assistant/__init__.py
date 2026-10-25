"""The in-app Assistant: a Claude tool-use loop over the platform's own services.

Read tools run immediately; consequential tools never act on their own — they return a
signed, expiring confirmation token, and only ``POST /assistant/confirm`` executes it.
"""
