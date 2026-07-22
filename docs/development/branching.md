# Branching and delivery

## Hierarchy

```text
main -> dev/<release-or-epic> -> feat/<vertical-slice>
```

- `main`: release可能で全acceptanceがgreen
- `dev/*`: 複数featureを統合してcross-feature acceptanceを行うbranch
- `feat/*`: user-visibleな縦slice。test、implementation、docsを同じbranchに含める

## Merge policy

1. `feat/*`は対象`dev/*`から作る。
2. 小さなConventional Commitを積む。
3. formatter、lint、全testを通す。
4. `TASK.md`を更新する。
5. `--no-ff`で`dev/*`へmergeし、feature境界をhistoryに残す。
6. release acceptance後、`dev/*`を`main`へ`--no-ff` mergeする。

実装途中の直接push、history rewrite、force pushは行わない。
