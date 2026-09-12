"""
Automated unit verification for the Job Finder MCP Server.
"""

import os
import sys
import asyncio
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server import process_mcp_request, ALL_TOOLS

async def test_mcp_endpoints():
    print("Testing MCP initialize...")
    init_req = {"jsonrpc": "2.0", "id": 1, "method": "initialize"}
    init_res = await process_mcp_request(init_req)
    assert init_res["result"]["serverInfo"]["name"] == "job-finder-career-engine"
    print("✓ initialize passed.")

    print("Testing MCP tools/list...")
    list_req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    list_res = await process_mcp_request(list_req)
    tool_names = [t["name"] for t in list_res["result"]["tools"]]
    print(f"✓ Registered {len(tool_names)} tools: {', '.join(tool_names)}")
    assert len(tool_names) == 21

    print("Testing MCP calculate_ats_score tool execution...")
    sample_jd = """
    We are seeking a Senior Python Engineer with 5+ years of experience in FastAPI, Docker, and PostgreSQL.
    Responsibilities include building distributed systems and high-performance APIs.
    """
    sample_resume = {
        "skills": ["python", "fastapi", "postgresql", "docker", "git"],
        "experience": [
            {"title": "Software Engineer", "company": "Tech Corp", "dates": "2020 - Present", "description": "Built FastAPI microservices."}
        ]
    }
    call_req = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "calculate_ats_score",
            "arguments": {
                "job_description": sample_jd,
                "resume_data": sample_resume
            }
        }
    }
    call_res = await process_mcp_request(call_req)
    content = json.loads(call_res["result"]["content"][0]["text"])
    print(f"✓ ATS Calculation Result: Overall={content['overall_score']}%, Skills={content['skills_score']}%, Matched={content['matched_skills']}")
    assert content["overall_score"] > 0
    assert "fastapi" in [s.lower() for s in content["matched_skills"]]

    print("Testing MCP extract_seniority_salary tool execution...")
    sal_call = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "extract_seniority_salary",
            "arguments": {
                "title": "Lead Software Engineer",
                "text": "Salary £95,000 - £120,000 p.a. + equity"
            }
        }
    }
    sal_res = await process_mcp_request(sal_call)
    sal_content = json.loads(sal_res["result"]["content"][0]["text"])
    print(f"✓ Seniority/Salary result: Seniority={sal_content['seniority']}, Salary={sal_content['salary']}")
    assert sal_content["seniority"] == "Lead"

    print("\n🎉 ALL MCP AUTOMATED TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    asyncio.run(test_mcp_endpoints())
