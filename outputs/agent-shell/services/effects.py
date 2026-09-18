"""Deterministic validation and obvious hazards; other actions receive live Jev assessment.
No command allowlist. Unknown commands are assessed, not refused for being unknown.
"""
import re
from pathlib import PurePosixPath
VERSION=2

def verdict(decision,reason,argv,scope,effect):
    return dict(decision=decision,reason=reason,argv=argv,scope=scope,effect=effect,policy_version=VERSION)

def assess(argv,scope,depth=0):
    name=PurePosixPath(argv[0]).name
    args=argv[1:]
    text=' '.join(argv)
    # These are conservative hazard indicators, not an exhaustive safety classifier.
    destructive=(name in {'rm','rmdir','unlink','shred','wipefs','mkfs','fdisk','sfdisk','parted','dd','truncate','reboot','poweroff','shutdown','halt','userdel','groupdel'}
        or name.startswith('mkfs.')
        or bool(re.search(r'(?<![\w-])(rm\s|rmtree\s*\(|unlink\s*\(|DROP\s+(TABLE|DATABASE)|mkfs\.|wipefs\b)',text,re.I))
        or (name in ('apt','apt-get') and any(a in args for a in ('remove','purge','autoremove','autopurge')))
        or (name=='git' and args and args[0] in ('reset','clean','restore','checkout','rm','push'))
        or (name=='systemctl' and args and args[0] in ('stop','disable','mask','kill','isolate','reboot','poweroff'))
        or (name=='ip' and any(a in args for a in ('del','delete','set','flush','replace'))))
    if destructive:return verdict('approve','This action may delete or overwrite work, disrupt services, or remove access.',argv,scope,'potential_harm')
    # Preserve APT's concrete no-removal guard, without making package names an allowlist.
    if name in ('apt','apt-get') and args and args[0]=='install':
        packages=[a for a in args[1:] if a not in ('-y','--yes','--no-remove')]
        if packages and all(re.fullmatch(r'[a-z0-9][a-z0-9+.-]*',a) and not a.endswith('-') for a in packages):
            argv=['/usr/bin/apt-get','install','-y','--no-remove',*packages]
    return verdict('inspect','Assess this exact operation and its effects in the current context.',argv,scope,'unassessed')
