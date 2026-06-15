"""Smoke tests — RAG module only."""
import sys
import os
import tempfile
import shutil
from pathlib import Path

os.chdir(Path(__file__).parent.parent)
sys.path.insert(0, '.')

tests = []

# ── 1. RAG imports ──────────────────────────────────────────
try:
    from src.rag.chunker import CodeChunk, chunk_file, chunk_directory
    from src.rag.embedder import Embedder
    from src.rag.retriever import Retriever
    from src.rag.indexer import Indexer, Index
    tests.append(('rag_imports', True))
except Exception as e:
    tests.append(('rag_imports', False, str(e)))

# ── 2. Chunker: basic ───────────────────────────────────────
try:
    src = 'def foo():\n    """Do foo."""\n    pass\n\ndef bar():\n    pass\n'
    chunks = chunk_file('test.py', src)
    assert len(chunks) == 2, f'expected 2, got {len(chunks)}'
    assert chunks[0].symbol_name == 'foo'
    assert chunks[0].symbol_type == 'function'
    assert chunks[0].start_line == 1
    assert chunks[0].end_line == 3
    assert chunks[1].symbol_name == 'bar'
    assert chunks[1].context == ['foo']
    tests.append(('chunk_basic', True))
except Exception as e:
    tests.append(('chunk_basic', False, str(e)))

# ── 3. Chunker: class with methods ──────────────────────────
try:
    src = 'class World:\n    def greet(self):\n        pass\n'
    chunks = chunk_file('test.py', src)
    assert len(chunks) == 2, f'expected 2, got {len(chunks)}'
    assert chunks[0].symbol_name == 'World'
    assert chunks[0].symbol_type == 'class'
    assert chunks[1].symbol_name == 'World.greet'
    assert chunks[1].symbol_type == 'function'
    tests.append(('chunk_class', True))
except Exception as e:
    tests.append(('chunk_class', False, str(e)))

# ── 4. Chunker: module fallback ─────────────────────────────
try:
    src = 'import os\nx = 1\n'
    chunks = chunk_file('utils.py', src)
    assert len(chunks) == 1
    assert chunks[0].symbol_type == 'module'
    tests.append(('chunk_module', True))
except Exception as e:
    tests.append(('chunk_module', False, str(e)))

# ── 5. Chunker: directory scan ──────────────────────────────
try:
    td = tempfile.mkdtemp()
    os.makedirs(os.path.join(td, 'pkg'))
    with open(os.path.join(td, 'pkg', 'a.py'), 'w') as f:
        f.write('def f1(): pass\n\nclass C1:\n    def m1(self): pass\n')
    with open(os.path.join(td, 'pkg', 'b.py'), 'w') as f:
        f.write('def f2(): pass\n')
    chunks = chunk_directory(td, 'pkg/**/*.py')
    assert len(chunks) == 4, f'expected 4, got {len(chunks)}'  # f1, C1, C1.m1, f2
    names = {c.symbol_name for c in chunks}
    assert 'f1' in names and 'f2' in names and 'C1' in names and 'C1.m1' in names
    tests.append(('chunk_directory', True))
except Exception as e:
    tests.append(('chunk_directory', False, str(e)))
finally:
    shutil.rmtree(td, ignore_errors=True)

# ── 6. Embedder: fit + transform ────────────────────────────
try:
    docs = ['def add(a,b): return a+b', 'class User: pass', 'def delete(x): pass']
    emb = Embedder(max_features=100)
    vecs = emb.fit(docs)
    assert vecs.shape[0] == 3, f'shape: {vecs.shape}'
    assert emb.fitted
    q = emb.embed_query('remove something')
    assert q.shape[0] == 1
    tests.append(('embedder', True))
except Exception as e:
    tests.append(('embedder', False, str(e)))

# ── 7. Embedder: save/load ──────────────────────────────────
try:
    td = tempfile.mkdtemp()
    docs = ['def add(a,b): return a+b', 'class User: pass']
    emb = Embedder()
    emb.fit(docs)
    emb.save(os.path.join(td, 'emb.pkl'))
    emb2 = Embedder()
    emb2.load(os.path.join(td, 'emb.pkl'))
    assert emb2.fitted
    assert emb2._chunk_vectors.shape[0] == 2
    tests.append(('embedder_io', True))
except Exception as e:
    tests.append(('embedder_io', False, str(e)))
finally:
    shutil.rmtree(td, ignore_errors=True)

# ── 8. Retriever: semantic search ───────────────────────────
try:
    docs = ['def add(a,b): return a+b', 'class User: pass',
            'def delete(x): pass', 'def create_user(): pass']
    emb = Embedder()
    emb.fit(docs)
    chunks_data = [
        CodeChunk('f.py', 'add', 'function', 1, 1, docs[0], [], docs[0].split(':')[0]),
        CodeChunk('f.py', 'User', 'class', 2, 2, docs[1], [], docs[1].split(':')[0]),
        CodeChunk('f.py', 'delete', 'function', 3, 3, docs[2], [], docs[2].split(':')[0]),
        CodeChunk('f.py', 'create_user', 'function', 4, 4, docs[3], [], docs[3].split(':')[0]),
    ]
    ret = Retriever(emb, chunks_data, coarse_k=3, fine_k=2)

    # search returns results in correct format
    r = ret.search('remove something', top_k=2)
    assert len(r) == 2
    assert r[0]['rank'] == 1
    assert r[0]['file'] == 'f.py'
    assert 'score' in r[0]
    assert 'code' in r[0]
    assert 'symbol' in r[0]
    tests.append(('retriever_search', True))
except Exception as e:
    tests.append(('retriever_search', False, str(e)))

# ── 9. Retriever: search_raw returns CodeChunks ─────────────
try:
    docs = ['def add(a,b): return a+b', 'class User: pass']
    emb = Embedder()
    emb.fit(docs)
    chunks_data = [
        CodeChunk('f.py', 'add', 'function', 1, 1, docs[0], [], ''),
        CodeChunk('f.py', 'User', 'class', 2, 2, docs[1], [], ''),
    ]
    ret = Retriever(emb, chunks_data)
    raw = ret.search_raw('math', top_k=1)
    assert len(raw) == 1
    assert isinstance(raw[0], CodeChunk)
    tests.append(('retriever_raw', True))
except Exception as e:
    tests.append(('retriever_raw', False, str(e)))

# ── 10. Indexer: build + persist + reload ───────────────────
try:
    td = tempfile.mkdtemp()
    src_dir = os.path.join(td, 'mylib')
    os.makedirs(src_dir)
    with open(os.path.join(src_dir, 'mod.py'), 'w') as f:
        f.write('def hello(): pass\n\nclass World:\n    def greet(self): pass\n')
    with open(os.path.join(src_dir, 'util.py'), 'w') as f:
        f.write('import os\n\ndef helper(): return 1\n')

    idxr = Indexer(os.path.join(td, '.rag_index'))
    idx = idxr.build(td, 'mylib/**/*.py')

    # 3 chunks from mod.py (hello, World, World.greet) + 1 from util.py (helper)
    assert len(idx.chunks) == 4, f'expected 4, got {len(idx.chunks)}'
    assert idx.file_count == 2
    assert idx.source_root == str(Path(td).resolve())

    # Check persistence files
    rag_dir = os.path.join(td, '.rag_index')
    assert os.path.exists(os.path.join(rag_dir, 'embedder.pkl'))
    assert os.path.exists(os.path.join(rag_dir, 'chunks.json'))
    assert os.path.exists(os.path.join(rag_dir, 'chunks.pkl'))
    assert os.path.exists(os.path.join(rag_dir, 'meta.json'))

    # Reload
    idx2 = idxr.load()
    assert len(idx2.chunks) == 4

    # Search via reloaded
    from src.rag.retriever import Retriever
    ret = Retriever(idx2.embedder, idx2.chunks)
    r = ret.search('greeting', top_k=2)
    assert len(r) <= 2
    tests.append(('indexer', True))
except Exception as e:
    tests.append(('indexer', False, str(e)))
finally:
    shutil.rmtree(td, ignore_errors=True)

# ── 11. Indexer: force rebuild ──────────────────────────────
try:
    td = tempfile.mkdtemp()
    src_dir = os.path.join(td, 'lib')
    os.makedirs(src_dir)
    with open(os.path.join(src_dir, 'x.py'), 'w') as f:
        f.write('def old(): pass\n')

    idxr = Indexer(os.path.join(td, '.rag_index'))
    idx1 = idxr.build(td, 'lib/**/*.py')

    # Modify file
    with open(os.path.join(src_dir, 'x.py'), 'w') as f:
        f.write('def old(): pass\n\ndef new_func(): pass\n')

    idx2 = idxr.build(td, 'lib/**/*.py', force=True)
    assert len(idx2.chunks) == 2, f'expected 2 after rebuild, got {len(idx2.chunks)}'
    tests.append(('indexer_force', True))
except Exception as e:
    tests.append(('indexer_force', False, str(e)))
finally:
    shutil.rmtree(td, ignore_errors=True)

# ── 12. Real-world: index agent-core src ────────────────────
try:
    chunks = chunk_directory('.', 'src/**/*.py')
    assert len(chunks) >= 100, f'expected 100+, got {len(chunks)}'

    # Verify key symbols exist
    names = {c.symbol_name for c in chunks}
    expected = ['HookManager', 'CompressionPipeline', 'Scratchpad', 'TodoManager',
                'Embedder', 'Retriever', 'Indexer', 'ToolRegistry']
    for name in expected:
        assert name in names, f'missing: {name}'
    tests.append(('real_world_index', True))
except Exception as e:
    tests.append(('real_world_index', False, str(e)))

# ── Results ─────────────────────────────────────────────────
passed = sum(1 for t in tests if t[1])
failed = [(t[0], t[2]) for t in tests if not t[1]]
print(f'RAG tests: {passed}/{len(tests)} passed')
if failed:
    for name, err in failed:
        print(f'  FAIL {name}: {err}')
else:
    print('All RAG tests passed!')
