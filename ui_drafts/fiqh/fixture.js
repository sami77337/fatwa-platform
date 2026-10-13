// Public heading metadata only. All titles and citations are synthetic.
export const FIXTURE_ID = "s2-synthetic-11397-v1";
export const PAGE_SIZE = 20;
export const SOURCE = Object.freeze({
  work_id: "synthetic-622",
  work_title: "مرجع فقهي حنبلي تجريبي",
  edition: "طبعة مصطنعة لا تمثل طبعة المصدر",
  madhhab: "حنبلي",
  synthetic: true,
});
const arabic = new Intl.NumberFormat("ar", { useGrouping: false });
export function createFixture() {
  const nodes = [];
  const children = new Map();
  const add = (parent, title, kind = "heading") => {
    const id = "fixture-" + String(nodes.length + 1).padStart(5, "0");
    const node = {
      id, parent_id: parent?.id ?? null, root_id: parent?.root_id ?? id,
      title, kind, depth: parent ? parent.depth + 1 : 1,
      position: parent ? (children.get(parent.id)?.length ?? 0) : nodes.filter(n => n.parent_id === null).length,
      child_count: 0, has_children: false,
      source: { ...SOURCE, printed_part: 1 + Math.floor(nodes.length / 2000), printed_page: 1 + nodes.length % 500 },
    };
    nodes.push(node);
    if (parent) {
      if (!children.has(parent.id)) children.set(parent.id, []);
      children.get(parent.id).push(node);
      parent.child_count++;
      parent.has_children = true;
    }
    return node;
  };
  add(null, "مقدمة تجريبية أولى", "introduction");
  add(null, "مقدمة تجريبية ثانية", "introduction");
  for (let book = 0; book < 30; book++) {
    const root = add(null, "كتاب تجريبي " + arabic.format(book + 1), "book");
    const fourthLevel = [];
    for (let chapter = 0; chapter < 24; chapter++) {
      const second = add(root, "باب تجريبي " + arabic.format(chapter + 1) + " من " + root.title);
      for (let section = 0; section < 2; section++) {
        const third = add(second, "فصل تجريبي " + arabic.format(section + 1) + " في " + second.title);
        for (let topic = 0; topic < 2; topic++) fourthLevel.push(add(third, "مبحث تجريبي " + arabic.format(topic + 1) + " في " + third.title));
      }
    }
    const leafCount = 210 + (book < 25 ? 1 : 0);
    for (let leaf = 0; leaf < leafCount; leaf++) {
      const parent = fourthLevel[leaf % fourthLevel.length];
      add(parent, "عنوان تجريبي " + arabic.format(leaf + 1) + " في " + root.title);
    }
  }
  return { id: FIXTURE_ID, nodes, children, byId: new Map(nodes.map(n => [n.id, n])) };
}
export function normalizeQuery(value) {
  return value.normalize("NFKC").replace(/[\u064b-\u065f\u0670\u0640]/gu, "")
    .replace(/[أإآٱ]/gu, "ا").replace(/ى/gu, "ي").replace(/\s+/gu, " ").trim();
}
