#!/bin/sh
# 拦截敏感文件 / 密钥提交（源自 PA_Agent 上游实践，适配 QuantHub 路径）
# 作为 pre-commit 的 local hook 运行：bash tools/block_secrets.sh
set -e

staged=$(git diff --cached --name-only --diff-filter=ACM)
[ -z "$staged" ] && exit 0

for path in $staged; do
	case "$path" in
		apps/pa_agent/config/settings.json|apps/pa_agent/config/settings.local.json|\
		apps/pa_agent/config/exception_state.json|apps/pa_agent/config/secret.key)
			echo "pre-commit: blocked sensitive file: $path"
			exit 1
			;;
		.env|.env.*)
			echo "pre-commit: blocked env file: $path"
			exit 1
			;;
		logs/*|.cache/*)
			echo "pre-commit: blocked log/cache file: $path"
			exit 1
			;;
		records/pending/*.json|records/pending/*.jsonl|\
		apps/pa_agent/records/pending/*.json|apps/pa_agent/records/pending/*.jsonl)
			echo "pre-commit: blocked analysis record: $path"
			exit 1
			;;
	esac
done

# 扫描 staged diff 是否含有密钥明文（api_key / api_key_encrypted / sk-...）
if git diff --cached -U0 | grep '^+' | grep -v '^+++' | grep -E \
	'api_key_encrypted["[:space:]]*:[[:space:]]*"[A-Za-z0-9+/=]{20,}"|"api_key"[[:space:]]*:[[:space:]]*"[^*]{8,}"|sk-[A-Za-z0-9]{12,}' \
	>/dev/null 2>&1; then
	echo "pre-commit: staged diff may contain API key material (api_key / api_key_encrypted / sk-...)"
	echo "Unstage those changes; keep secrets in config/settings.json (gitignored) only."
	exit 1
fi

exit 0
