import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from tugraph_homework.common import DEFAULT_URI, DEFAULT_USER, DEFAULT_PASSWORD
from lgraph_python import *

def check_graph(graph_name):
    galaxy = PyGalaxy(DEFAULT_URI)
    galaxy.SetUser(DEFAULT_USER, DEFAULT_PASSWORD)
    db = galaxy.OpenGraph(graph_name, True)
    txn = db.CreateReadTxn()
    
    node_count = 0
    vit = txn.GetVertexIterator()
    while vit.IsValid():
        node_count += 1
        vit.Next()
        
    edge_count = 0
    vit = txn.GetVertexIterator()
    while vit.IsValid():
        eit = vit.GetOutEdgeIterator()
        while eit.IsValid():
            edge_count += 1
            eit.Next()
        vit.Next()
        
    print(f"Graph: {graph_name}")
    print(f"Nodes: {node_count}")
    print(f"Edges: {edge_count}")
    txn.Abort()

if __name__ == "__main__":
    check_graph("hcg")
