"""The Claude directory reads the human-readable tool name from annotations.title; every tool must carry it."""
import asyncio


def test_every_tool_has_an_annotation_title_equal_to_its_title(service):
    from cp0x_mcp.server import build_server

    tools = asyncio.run(build_server(service).list_tools())
    assert len(tools) == 12
    for tool in tools:
        assert tool.title, tool.name
        assert tool.annotations is not None and tool.annotations.title == tool.title, tool.name
        assert tool.annotations.read_only_hint is True and tool.annotations.destructive_hint is False, tool.name
    assert len({tool.annotations.title for tool in tools}) == 12  # no shared annotation object with one title
