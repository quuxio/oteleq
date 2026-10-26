printf 'sha=%s\n' "$(git rev-parse HEAD)" >> "$GITHUB_OUTPUT"
