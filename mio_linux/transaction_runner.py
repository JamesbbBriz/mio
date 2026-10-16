"""Unprivileged terminal bridge: manager output and confirmation stay in the TTY."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time


def main():
    request = Path(sys.argv[1])
    data = json.loads(request.read_text())
    result = Path(data['result'])
    def report(state, **extra):
        temporary = result.with_suffix('.tmp')
        temporary.write_text(json.dumps({'state': state, 'time': time.time(), **extra}))
        os.replace(temporary, result)
    print('Mio · 系统操作\n' + shlex.join(data['argv']), flush=True)
    report('running')
    try:
        # A second prompt covers noninteractive managers such as snap remove.
        if input('\n确认执行以上命令？输入 YES 继续，其他输入取消：') != 'YES':
            report('cancelled')
            return
        status = subprocess.call(data['argv'])
        report('finished', returncode=status)
        print(f'\n操作退出状态：{status}。详细结果请查看上方包管理器输出。')
    except (EOFError, KeyboardInterrupt):
        report('interrupted')
    except Exception as error:
        report('failed', error=str(error))
    try:
        input('\n按回车关闭窗口…')
    except (EOFError, KeyboardInterrupt):
        pass


if __name__ == '__main__':
    main()
