#!/usr/bin/env python3
"""
CLI tool for users to quickly view, configure, or update their profile & job search preferences.
Usage:
    python backend/mcp/cli_profile.py show
    python backend/mcp/cli_profile.py set --roles "AI Engineer,LLM Engineer" --locations "London,Remote" --timeframe "past_24_hours" --ats 65
    python backend/mcp/cli_profile.py interactive
"""

import sys
import os
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mcp.tools.profile_tools import load_profile_data, PROFILE_CONFIG_PATH

def show_profile():
    data = load_profile_data()
    if not data:
        print("❌ No profile found. Run `cli_profile.py interactive` to set up your profile.")
        return
    print("\n================ ACTIVE CANDIDATE CONFIG ================")
    cand = data.get("candidate", {})
    prefs = data.get("search_preferences", {})
    print(f"👤 Name:       {cand.get('name', 'N/A')}")
    print(f"📧 Email:      {cand.get('email', 'N/A')}")
    print(f"📍 Location:   {cand.get('location', 'N/A')}")
    print(f"🎯 Roles:      {', '.join(prefs.get('target_roles', []))}")
    print(f"🌍 Locations:  {', '.join(prefs.get('target_locations', []))}")
    print(f"⏱️  Timeframe:  {prefs.get('timeframe', 'N/A')}")
    print(f"📊 Min ATS:    {prefs.get('min_ats_score_threshold', 'N/A')}%")
    print(f"📁 Config:     {PROFILE_CONFIG_PATH}")
    print("=========================================================\n")

def set_profile(args):
    data = load_profile_data()
    cand = data.setdefault("candidate", {})
    prefs = data.setdefault("search_preferences", {})

    if args.name: cand["name"] = args.name
    if args.email: cand["email"] = args.email
    if args.location: cand["location"] = args.location
    if args.roles: prefs["target_roles"] = [r.strip() for r in args.roles.split(",") if r.strip()]
    if args.locations: prefs["target_locations"] = [l.strip() for l in args.locations.split(",") if l.strip()]
    if args.timeframe: prefs["timeframe"] = args.timeframe
    if args.ats: prefs["min_ats_score_threshold"] = float(args.ats)

    os.makedirs(os.path.dirname(PROFILE_CONFIG_PATH), exist_ok=True)
    with open(PROFILE_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print("✅ Profile and preferences successfully updated!")
    show_profile()

def main():
    parser = argparse.ArgumentParser(description="Candidate Profile & Job Preferences CLI")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("show", help="Display current profile and preferences")

    set_parser = subparsers.add_parser("set", help="Update profile and preferences")
    set_parser.add_argument("--name", help="Candidate name")
    set_parser.add_argument("--email", help="Candidate email")
    set_parser.add_argument("--location", help="Base location")
    set_parser.add_argument("--roles", help="Comma-separated target roles")
    set_parser.add_argument("--locations", help="Comma-separated target locations")
    set_parser.add_argument("--timeframe", help="Search timeframe (e.g. past_24_hours)")
    set_parser.add_argument("--ats", help="Min ATS score threshold (e.g. 65)")

    args = parser.parse_args()
    if args.command == "show" or not args.command:
        show_profile()
    elif args.command == "set":
        set_profile(args)

if __name__ == "__main__":
    main()
