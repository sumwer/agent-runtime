from mcp.server.fastmcp import FastMCP

from mock_mcp.fixtures import build

mcp = FastMCP('opik-mock')
DATA = build()


def paginate(rows, page, page_size):
    if page < 1 or not 1 <= page_size <= 100:
        raise ValueError('page >= 1 and 1 <= page_size <= 100 required')
    start = (page - 1) * page_size
    return {'items': rows[start:start + page_size], 'total': len(rows),
            'page': page, 'page_size': page_size}


@mcp.tool()
def list_experiments() -> list[dict]:
    """List evaluation experiments with counts and average scores."""
    return [{'id': k, 'name': v['name'], 'trace_count': len(v['traces']),
             'avg_score': sum(t['score'] for t in v['traces']) / len(v['traces'])}
            for k, v in DATA.items()]


@mcp.tool()
def get_traces(experiment_id: str, page: int = 1, page_size: int = 50,
               max_score: float | None = None, min_score: float | None = None) -> dict:
    """Page experiment traces; optional score filters are inclusive."""
    rows = DATA[experiment_id]['traces']
    rows = [r for r in rows if (max_score is None or r['score'] <= max_score)
            and (min_score is None or r['score'] >= min_score)]
    return paginate(rows, page, page_size)


@mcp.tool()
def get_scores(experiment_id: str, page: int = 1, page_size: int = 50) -> dict:
    """Page trace IDs and numerical scores."""
    return paginate([{'trace_id': r['id'], 'score': r['score']}
                     for r in DATA[experiment_id]['traces']], page, page_size)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--transport', choices=['stdio', 'streamable-http'], default='stdio')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    mcp.settings.host = '127.0.0.1'
    mcp.settings.port = args.port
    mcp.run(transport=args.transport)
