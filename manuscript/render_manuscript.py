"""Use the packaged DOCX renderer with an isolated Linux LibreOffice adapter.

The Windows runtime has bundled Python and Poppler, but no LibreOffice.
This adapter uses the existing document-render image, not a desktop installation.
"""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path('C:/Users/nurto/.cache/codex-runtimes/codex-primary-runtime/dependencies')
SKILL = Path('C:/Users/nurto/.codex/plugins/cache/openai-primary-runtime/documents/26.1030.10813/skills/documents')
os.environ['PATH'] = str(RUNTIME / 'native/poppler/Library/bin') + os.pathsep + os.environ['PATH']
spec = importlib.util.spec_from_file_location('packaged_render_docx', SKILL / 'render_docx.py')
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)


def container_convert(doc_path, user_profile, convert_tmp_dir, stem, verbose=False):
    source = Path(doc_path).resolve()
    dest = Path(convert_tmp_dir).resolve()
    cmd = ['docker', 'run', '--rm', '--network', 'none', '--cap-drop', 'ALL',
           '--security-opt', 'no-new-privileges:true', '--memory', '1g', '--cpus', '2',
           '--mount', f'type=bind,source={source.parent},target=/input,readonly',
           '--mount', f'type=bind,source={dest},target=/out',
           'applied-soft-doc-render:local', '/usr/bin/soffice',
           '-env:UserInstallation=file:///tmp/thesis-document-profile',
           '--headless', '--norestore', '--convert-to', 'pdf', '--outdir', '/out', '/input/' + source.name]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    output = result.stdout + result.stderr
    if verbose:
        print(output)
    (ROOT / 'manuscript/qa').mkdir(exist_ok=True)
    (ROOT / 'manuscript/qa/render.log').write_text(output, encoding='utf-8')
    result.check_returncode()
    pdf = dest / (source.stem + '.pdf')
    if not pdf.exists() or not pdf.stat().st_size:
        raise RuntimeError(output)
    return str(pdf), output


renderer.convert_to_pdf = container_convert
if __name__ == '__main__':
    sys.argv = [str(SKILL / 'render_docx.py'), str(ROOT / 'manuscript/Federated_Edge_IDS_Manuscript_v1.docx'),
                '--output_dir', str(ROOT / 'manuscript/qa/pages'), '--dpi', '140', '--emit_pdf']
    renderer.main()
