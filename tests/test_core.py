import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from opensync.adapters import Document, extract, local_documents, normalize, snapshot
from opensync.core import KnowledgeBase, chunks, writer_lock


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.folder = self.root / 'notes'
        self.folder.mkdir()
        self.file = self.folder / 'guide.md'
        self.file.write_text('# Robotics\nPlanning uses state transitions.\nPersian فارسی دانش\n')
        self.kb = KnowledgeBase(self.root / 'kb')
        self.addCleanup(self.kb.db.close)
        self.ident = self.kb.register(str(self.folder), 'local', 3600)

    def test_index_search_read_and_citations(self):
        self.assertEqual(self.kb.refresh(self.ident)['added'], 1)
        hit = self.kb.search('state transitions')[0]
        self.assertEqual(hit['location'], str(self.file))
        self.assertEqual(hit['title'], 'Robotics')
        self.assertFalse(hit['stale'])
        self.assertEqual(hit['line_start'], 1)
        self.assertIn('Planning', self.kb.read(hit['document_id'])['text'])
        self.assertEqual(len(self.kb.search('فارسی')), 1)

    def test_incremental_edit_and_deletion(self):
        self.kb.refresh(self.ident)
        self.assertEqual(self.kb.refresh(self.ident)['unchanged'], 1)
        before = self.kb.search('planning')[0]['document_id']
        self.file.write_text('# Robots\nLearning by interaction\n')
        self.assertEqual(self.kb.refresh(self.ident)['updated'], 1)
        self.assertEqual(self.kb.search('planning'), [])
        self.assertEqual(self.kb.search('learning')[0]['document_id'], before)
        self.file.unlink()
        self.assertEqual(self.kb.refresh(self.ident)['deleted'], 1)
        self.assertEqual(self.kb.search('learning'), [])

    def test_failure_keeps_complete_snapshot(self):
        self.kb.refresh(self.ident)
        self.file.write_text('changed content')
        (self.folder / 'broken.txt').write_bytes(b'\xff\x00')
        result = self.kb.refresh(self.ident)
        self.assertFalse(result['ok'])
        self.assertEqual(len(self.kb.search('planning')), 1)
        self.assertEqual(self.kb.search('changed'), [])
        self.assertTrue(self.kb.search('planning')[0]['stale'])
        self.assertFalse(self.kb.history()[0]['ok'])

    def test_missing_source_keeps_snapshot(self):
        self.kb.refresh(self.ident)
        self.file.unlink()
        self.folder.rmdir()
        self.assertFalse(self.kb.refresh(self.ident)['ok'])
        self.assertEqual(len(self.kb.search('planning')), 1)

    def test_transaction_failure_rolls_back_every_change(self):
        self.kb.refresh(self.ident)
        self.file.write_text('changed')
        original = chunks
        def fail(body):
            yield 1, 1, 'changed'
            raise ValueError('mid-transaction failure')
        with patch('opensync.core.chunks', fail):
            self.assertFalse(self.kb.refresh(self.ident)['ok'])
        self.assertEqual(len(self.kb.search('planning')), 1)
        self.assertEqual(self.kb.search('changed'), [])

    def test_dedup_pause_resume_due_remove(self):
        self.assertEqual(self.kb.register(str(self.folder), 'local', 300), self.ident)
        self.kb.refresh_due()
        self.assertEqual(self.kb.refresh_due(), [])
        self.kb.pause(self.ident)
        self.assertEqual(self.kb.refresh_due(force=True), [])
        self.kb.pause(self.ident, False)
        self.assertEqual(len(self.kb.refresh_due()), 1)
        self.kb.remove(self.ident)
        self.assertEqual(self.kb.sources(), [])
        self.assertEqual(self.kb.search('planning'), [])
        self.assertTrue(self.file.exists())

    def test_source_filter_and_any(self):
        self.kb.refresh(self.ident)
        two = self.root / 'second.txt'
        two.write_text('state machines')
        ident = self.kb.register(str(two), 'local', 60)
        self.kb.refresh(ident)
        self.assertEqual(len(self.kb.search('state', source=ident)), 1)
        self.assertEqual(len(self.kb.search('planning machines')), 0)
        self.assertEqual(len(self.kb.search('planning machines', any_word=True)), 2)

    def test_search_escapes_fts_operators(self):
        self.kb.refresh(self.ident)
        self.assertEqual(len(self.kb.search('"planning"')), 1)
        self.assertEqual(self.kb.search('planning OR sabotage'), [])
        for query in ('', '*', 'word ' * 65):
            with self.assertRaises(ValueError):
                self.kb.search(query)
        with self.assertRaises(ValueError):
            self.kb.search('planning', limit=-1)

    def test_read_and_history_bounds(self):
        self.kb.refresh(self.ident)
        ident = self.kb.search('planning')[0]['document_id']
        self.assertEqual(self.kb.read(ident, 2, 1)['text'], 'Planning uses state transitions.')
        with self.assertRaises(ValueError):
            self.kb.read(ident, 0)
        with self.assertRaises(ValueError):
            self.kb.history(limit=1000)

    def test_readers_observe_last_committed_snapshot(self):
        self.kb.refresh(self.ident)
        with KnowledgeBase(self.kb.home) as reader:
            with self.kb.db:
                self.kb.db.execute('DELETE FROM passages')
                self.assertEqual(len(reader.search('planning')), 1)
            self.assertEqual(reader.search('planning'), [])

    def test_history_is_bounded(self):
        with self.kb.db:
            for i in range(110):
                self.kb._record(self.ident, i, True, {})
        self.assertEqual(self.kb.db.execute('SELECT count(*) FROM runs').fetchone()[0], 100)


class AdapterTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize('HTTPS://Example.com#part'), ('https://example.com/', 'url'))
        self.assertEqual(normalize('git+https://github.com/a/b.git')[1], 'git')
        for uri in ('https://user:pw@example.com', 'ftp://example.com', 'git+https://a/b?token=x'):
            with self.assertRaises(ValueError):
                normalize(uri)

    def test_html_text_title_and_hidden_content(self):
        doc = extract(b'<head><title>Title</title><style>secret</style></head><h1>Visible</h1><p>Next</p><script>bad</script>', 'https://example.com', html=True)
        self.assertEqual(doc.title, 'Title')
        self.assertEqual(doc.body, 'Visible\nNext')

    def test_binary_and_decode_failure(self):
        for data in (b'abc\0', b'\xff'):
            with self.assertRaises(ValueError):
                extract(data, 'a.txt')

    def test_chunks_bound_long_lines(self):
        result = list(chunks('x' * 20001 + '\nlast'))
        self.assertTrue(all(len(c[2]) <= 8000 for c in result))
        self.assertEqual(result[-1], (2, 2, 'last'))
        self.assertEqual(list(chunks('')), [])

    def test_ignore_symlinks_and_private_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'keep.md').write_text('safe')
            (root / '.env').write_text('secret')
            (root / 'private.txt').write_text('secret')
            (root / '.opensyncignore').write_text('private.txt\n')
            (root / 'node_modules').mkdir()
            (root / 'node_modules' / 'bad.txt').write_text('ignored')
            try:
                (root / 'link.txt').symlink_to(root / 'keep.md')
            except OSError:
                pass  # Windows runners may lack symlink privileges.
            self.assertEqual([d.body for d in local_documents(root)], ['safe'])

    def test_web_adapter_closes_stream_and_checks_type(self):
        class Response(io.BytesIO):
            from email.message import Message
            headers = Message()
            headers['Content-Type'] = 'text/html; charset=utf-8'
        response = Response(b'<p>web planning</p>')
        with patch('opensync.adapters.build_opener') as opener:
            opener.return_value.open.return_value = response
            doc = snapshot('https://example.com/', 'url', Path('/tmp'))[0]
            self.assertEqual(doc.body, 'web planning')
            self.assertTrue(response.closed)

    def test_snapshot_size_limit(self):
        with patch('opensync.adapters.web_document', return_value=Document('a', 'a', '12345')), patch('opensync.adapters.MAX_SNAPSHOT_BYTES', 4):
            with self.assertRaises(ValueError):
                snapshot('https://example.com', 'url', Path('/tmp'))

    def test_docx(self):
        import zipfile
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, 'w') as z:
            z.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Hello</w:t></w:r></w:p></w:body></w:document>')
        self.assertEqual(extract(raw.getvalue(), 'a.docx', '.docx').body, 'Hello')


if __name__ == '__main__':
    unittest.main()
