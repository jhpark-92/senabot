import json
import re

def strip_parens(name):
    """괄호와 그 안 내용을 제거 (예: '델오(오르카)란' -> '델오란')"""
    return re.sub(r'\(.*?\)', '', name).strip()

def normalize(s):
    """글자를 정렬해서 순서 상관없이 비교 가능하게 함"""
    return ''.join(sorted(s))

with open('guide_data.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# 같은 덱으로 볼 수 있는 것들끼리 그룹화
groups = {}
for name, info in data.items():
    core = strip_parens(name)
    key = normalize(core)
    groups.setdefault(key, []).append((name, info))

merged = {}
report = []

for key, entries in groups.items():
    if len(entries) == 1:
        name, info = entries[0]
        merged[name] = info
        continue

    # 대표 이름 선택: 괄호 없는 것 중 가장 짧은 것 우선
    names_no_parens = [n for n, _ in entries if '(' not in n]
    if names_no_parens:
        canonical = min(names_no_parens, key=len)
    else:
        canonical = min([n for n, _ in entries], key=len)

    all_counters = []
    all_priority = []
    all_equipment = []
    all_notes = []

    for name, info in entries:
        for c in info.get('counter_decks', []):
            if c not in all_counters:
                all_counters.append(c)
        for field, bucket in [
            ('priority_note', all_priority),
            ('equipment', all_equipment),
            ('notes', all_notes),
        ]:
            val = (info.get(field) or '').strip()
            if val and val not in bucket:
                bucket.append(val)

    merged[canonical] = {
        'counter_decks': all_counters,
        'priority_note': ' / '.join(all_priority),
        'equipment': ' / '.join(all_equipment),
        'notes': ' / '.join(all_notes),
    }
    report.append((canonical, [n for n, _ in entries]))

with open('guide_data.json', 'w', encoding='utf-8') as f:
    json.dump(merged, f, ensure_ascii=False, indent=2)

print(f"{len(data)}개 -> {len(merged)}개로 통합\n")
print("=== 병합된 항목들 ===")
for canonical, originals in report:
    print(f"  {originals} -> '{canonical}'")

if not report:
    print("  병합된 항목이 없습니다.")
