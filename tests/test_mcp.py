import sys
from octopus.mcp.protocol import JSONRPCClient

def test_mcp_internal_fs():
    print("Testing MCP Internal Filesystem Server...")
    
    # Setup client pointing to our own internal tool
    # Note: using 'py' or 'python' depending on env, but assuming sys.executable works best
    client = JSONRPCClient(
        command=sys.executable, 
        args=["-m", "octopus.tools.internal_fs_server"]
    )
    
    try:
        print("Starting Client...")
        client.start()
        print("Client Started. Initialized.")
        
        print("Calling tools/list...")
        tools = client.list_tools()
        
        print(f"Successfully retrieved {len(tools)} tools:")
        for t in tools:
            print(f" - {t.name}: {t.description}")
            
        if len(tools) >= 3:
            print("\n[PASS] MCP Protocol works correctly.")
        else:
            print("\n[FAIL] Not all tools retrieved.")
            
    except Exception as e:
        print(f"\n[FAIL] Exception: {e}")
    finally:
        client.stop()

if __name__ == "__main__":
    test_mcp_internal_fs()
