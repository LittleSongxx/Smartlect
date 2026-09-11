"""Exact current-config secret values only; never a complete security audit."""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tempfile
import uuid
import zipfile

ROOT=Path(__file__).resolve().parents[1]
CONFIGS=('run/runtime.env','run/model.env')
MIN_LENGTH=12
CHUNK=65536


def exclusion(name, *, current_configs=True):
    path=PurePosixPath(name.replace('\\','/'));lower=str(path).lower();base=path.name.lower()
    if base=='rag_cases.jsonl' or 'holdout' in lower or 'heldout' in lower:
        return 'protected_holdout_path_not_read'
    if not (current_configs and name in CONFIGS) and not base.endswith(('.example','.template','.sample')) and (
            base=='.env' or base.endswith('.env') or '.env.' in base or base.startswith('.env-')):
        return 'old_env_not_read'
    return None


def scan(root):
    root=root.resolve();errors=[];skipped=[];leaks=[];values={};config_read=[];short=[]
    def error(path,reason):errors.append({'path':str(path),'reason':reason})
    def local(path):return path.relative_to(root).as_posix()
    def checked(path):
        try:
            resolved=path.resolve(strict=True)
            resolved.relative_to(root)
            return resolved
        except (ValueError,RuntimeError):error(local(path),'escaping_or_cyclic_symlink');return None
        except OSError:error(local(path),'path_unreadable');return None
    for name in CONFIGS:
        path=root/name
        if path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode)!=0o600:
            error(name,'private_regular_configuration_required');continue
        if checked(path) is None:continue
        try:
            for line in path.read_text(encoding='utf-8').splitlines():
                if not line.strip() or line.lstrip().startswith('#'):continue
                key,separator,value=line.partition('=');key=key.strip();value=value.strip()
                if not separator or not re.fullmatch(r'[A-Z][A-Z0-9_]*',key):error(name,'unsupported_configuration_syntax');continue
                if len(value)>=2 and value[0]==value[-1] and value[0] in "\"'":value=value[1:-1]
                if not key.endswith(('_PASSWORD','_TOKEN','_SECRET','_API_KEY')):continue
                if len(value)<MIN_LENGTH:
                    short.append(key);continue
                values.setdefault(value,set()).add(key)
            config_read.append(name)
        except (OSError,UnicodeError):error(name,'configuration_read_failed')
    needles={value.encode('utf-8'):keys for value,keys in values.items()}
    if not needles:error('configuration','no_eligible_current_secret_values')
    overlap=max((len(value) for value in needles),default=1)-1
    def inspect(stream):
        tail=b'';found=set()
        while True:
            block=stream.read(CHUNK)
            if not block:break
            data=tail+block
            for value,keys in needles.items():
                if value in data:found.update(keys)
            tail=data[-overlap:] if overlap else b''
        return sorted(found)
    def file_paths(directory, *, required=True):
        if not directory.exists():
            if required:error(local(directory),'required_scan_directory_missing')
            return []
        if checked(directory) is None:return []
        if directory.is_symlink():error(local(directory),'directory_symlink_not_scanned');return []
        result=[]
        def failed(exc):error(local(directory),'directory_enumeration_failed')
        for current,dirs,files in os.walk(directory,followlinks=False,onerror=failed):
            for name in list(dirs):
                path=Path(current)/name
                if path.is_symlink():
                    if checked(path) is not None:error(local(path),'directory_symlink_not_scanned')
                    dirs.remove(name)
            result.extend(Path(current)/name for name in files)
        return result
    try:
        listed=subprocess.run(['git','ls-files','-z','--cached','--others','--exclude-standard'],cwd=root,
            capture_output=True,check=True).stdout.split(b'\0')
        candidates={root/os.fsdecode(name) for name in listed if name}
    except (OSError,subprocess.CalledProcessError):error('git','file_enumeration_failed');candidates=set()
    for directory in ('web/user/dist','web/admin/dist'):candidates.update(file_paths(root/directory))
    archives=sorted((p for p in file_paths(root/'handoff/sources') if p.suffix.lower()=='.zip'),key=str)
    archive_paths={resolved for p in archives if (resolved:=checked(p)) is not None}
    if not archives:error('handoff/sources','frozen_zip_archives_missing')
    files_scanned=members_scanned=archives_scanned=0
    for path in sorted(candidates,key=str):
        name=local(path)
        if not path.exists() and not path.is_symlink():
            skipped.append({'path':name,'reason':'not_present_in_worktree'});continue
        resolved=checked(path)
        if resolved is None:continue
        if resolved in archive_paths:
            skipped.append({'path':name,'reason':'archive_scanned_by_safe_members_only'});continue
        reason=exclusion(name) or exclusion(local(resolved))
        if reason:skipped.append({'path':name,'reason':reason});continue
        if not resolved.is_file():error(name,'not_a_regular_file');continue
        try:
            with resolved.open('rb') as stream:found=inspect(stream)
            files_scanned+=1
            if found:leaks.append({'path':name,'keys':found})
        except OSError:error(name,'file_read_failed')
    for path in archives:
        archive_name=local(path);resolved=checked(path)
        if resolved is None:continue
        try:
            with zipfile.ZipFile(resolved) as archive:
                archives_scanned+=1
                for member in archive.infolist():
                    if member.is_dir():continue
                    name=archive_name+'!/'+member.filename;parts=PurePosixPath(member.filename)
                    if parts.is_absolute() or '..' in parts.parts or '\\' in member.filename or re.match(r'^[A-Za-z]:',member.filename):
                        error(name,'unsafe_zip_member_path');continue
                    reason=exclusion(member.filename,current_configs=False)
                    if reason:skipped.append({'path':name,'reason':reason});continue
                    try:
                        with archive.open(member) as stream:
                            if stat.S_ISLNK(member.external_attr>>16):
                                target=stream.read(4097)
                                if len(target)>4096:error(name,'zip_symlink_target_too_long');continue
                                link=PurePosixPath(target.decode('utf-8'));depth=len(parts.parent.parts)
                                unsafe=link.is_absolute() or b'\\' in target or bool(re.match(rb'^[A-Za-z]:',target))
                                for part in link.parts:
                                    depth+=-1 if part=='..' else 0 if part=='.' else 1
                                    unsafe=unsafe or depth<0
                                if unsafe:error(name,'escaping_zip_symlink');continue
                                # ZIP links are inspected as stored link text, never followed or extracted.
                                found=sorted({key for value,keys in needles.items() if value in target for key in keys})
                            else:found=inspect(stream)
                        members_scanned+=1
                        if found:leaks.append({'path':name,'keys':found})
                    except (OSError,RuntimeError,UnicodeError,zipfile.BadZipFile):error(name,'zip_member_read_failed')
        except (OSError,RuntimeError,zipfile.BadZipFile):error(archive_name,'zip_archive_read_failed')
    report={'schema_version':'current-config-exact-secret-scan-v1','status':'FAILED' if errors or leaks else 'PASSED',
        'scope':'Exact UTF-8 values from current Smartlect runtime/model configuration only; not a complete security audit, history scan, or encoded-secret detector.',
        'configuration_files_read':config_read,'minimum_value_characters':MIN_LENGTH,
        'selected_keys':sorted({key for keys in values.values() for key in keys}),'unique_values_checked':len(values),
        'short_or_empty_keys_not_checked':sorted(set(short)),'files_scanned':files_scanned,
        'zip_archives_scanned':archives_scanned,'zip_members_scanned':members_scanned,
        'candidate_file_count':len(candidates),'leaks':leaks,'excluded_paths':skipped,'errors':errors,
        'selection':'All git-tracked files plus nonignored untracked files, both frontend dist trees, and decoded handoff/sources ZIP members; no ZIP extraction. Internal file symlinks resolve only inside Smartlect; directory symlinks fail closed.'}
    # A malicious filename can itself contain a secret. Never echo that value in a report path.
    encoded=json.dumps(report,ensure_ascii=True)
    for value in values:encoded=encoded.replace(json.dumps(value,ensure_ascii=True)[1:-1],'[REDACTED]')
    return json.loads(encoded)


def main(output=None):
    output=Path(output) if output else ROOT/'artifacts'/('secret-scan-'+uuid.uuid4().hex+'.json')
    if not output.is_absolute():output=ROOT/output
    try:
        output.resolve().relative_to(ROOT)
        if output.exists() or output.is_symlink():raise ValueError()
        report=scan(ROOT)
        output.parent.mkdir(parents=True,exist_ok=True)
        # Exclusive creation preserves every previous report, including under concurrent invocations.
        with output.open('x',encoding='utf-8') as stream:json.dump(report,stream,ensure_ascii=True,indent=2);stream.write('\n')
        print(json.dumps({'status':report['status'],'files_scanned':report['files_scanned'],'zip_members_scanned':report['zip_members_scanned'],
            'leak_locations':len(report['leaks']),'errors':len(report['errors']),'report_written':True}))
        return 0 if report['status']=='PASSED' else 1
    except (OSError,ValueError):
        print(json.dumps({'status':'FAILED','error':'scan_setup_or_new_report_path_invalid'}));return 2


def self_test():
    with tempfile.TemporaryDirectory() as directory,tempfile.TemporaryDirectory() as outside:
        root=Path(directory);secret='synthetic-private-value-123456';other='synthetic-model-value-654321'
        subprocess.run(['git','init','-q',str(root)],check=True,capture_output=True)
        (root/'run').mkdir();(root/'run/runtime.env').write_text('SMARTLECT_INTERNAL_TOKEN='+secret+'\nIGNORED_URL='+other+'\n')
        (root/'run/model.env').write_text('SMARTLECT_MODEL_API_KEY='+other+'\nSHORT_SECRET=tiny\n')
        for name in CONFIGS:(root/name).chmod(0o600)
        (root/'.gitignore').write_text('run/\nignored.txt\nweb/*/dist/\n')
        (root/'tracked.txt').write_text(secret);subprocess.run(['git','-C',str(root),'add','tracked.txt'],check=True,capture_output=True)
        (root/'untracked.txt').write_text(other);(root/'ignored.txt').write_text(secret)
        (root/'evals').mkdir();(root/'evals/rag_cases.jsonl').write_text(secret)
        (root/'holdout-result.json').write_text(other);(root/'rag-development-result.json').write_text(secret)
        (root/'old.env').write_text(secret);(root/'.env.example').write_text(secret)
        (root/'web/user/dist').mkdir(parents=True);(root/'web/admin/dist').mkdir(parents=True)
        (root/'web/user/dist/bundle.js').write_bytes(b'x'*(CHUNK-5)+secret.encode())
        (root/'web/admin/dist/bundle.js').write_text(other)
        (root/'handoff/sources').mkdir(parents=True)
        with zipfile.ZipFile(root/'handoff/sources/frozen.zip','w',zipfile.ZIP_STORED) as archive:
            archive.writestr('src/leak.py',secret);archive.writestr('evals/rag_cases.jsonl',other)
            archive.writestr('src/.env',other);archive.writestr('src/.env.example',other)
            archive.writestr('run/runtime.env',other)
        (root/'internal-link.txt').symlink_to(root/'untracked.txt')
        (root/(secret+'.txt')).write_text(secret)
        result=scan(root);locations={r['path'] for r in result['leaks']}
        assert {'tracked.txt','untracked.txt','rag-development-result.json','.env.example','web/user/dist/bundle.js',
                'web/admin/dist/bundle.js','internal-link.txt','handoff/sources/frozen.zip!/src/leak.py',
                'handoff/sources/frozen.zip!/src/.env.example'}<=locations
        assert not result['errors'] and result['zip_members_scanned']==2
        assert not {'ignored.txt','evals/rag_cases.jsonl','holdout-result.json','old.env'}&locations
        assert secret not in json.dumps(result) and other not in json.dumps(result)
        target=Path(outside)/'private.txt';target.write_text(secret);(root/'escape.txt').symlink_to(target)
        escaped=scan(root)
        assert any(r['path']=='escape.txt' and r['reason']=='escaping_or_cyclic_symlink' for r in escaped['errors'])
        assert all(r['path']!='escape.txt' for r in escaped['leaks'])
    print('Synthetic secret-scan self-test passed; no Smartlect configuration or real scan was read/run')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path);parser.add_argument('--self-test',action='store_true')
    args=parser.parse_args()
    if args.self_test:self_test()
    else:raise SystemExit(main(args.output))
