import assert from "node:assert/strict";

export function assertVerifiedReference(actual, expected) {
  assert.equal(actual.batch_id,expected.batch_id,"Citation belongs to another batch");
  assert.equal(actual.row_id,expected.row_id,"Citation belongs to another row");
  assert.equal(actual.question,expected.question,"Detail original question differs");
  assert.equal(actual.references.length,1,"Expected exactly the selected row's one reference");
  const reference=actual.references[0];
  assert.equal(reference.reference_ordinal,expected.reference_ordinal);
  assert.equal(reference.status,"VERIFIED","Reference status must be exactly VERIFIED");
  assert.equal(reference.original_pointer,expected.original_pointer,"Citation is attached to another source pointer");
  assert.ok(typeof expected.citation_text==="string"&&expected.citation_text.length>0,"Expected citation is mandatory");
  assert.ok(typeof expected.locator==="string"&&expected.locator.length>0,"Expected printed locator is mandatory");
  assert.equal(reference.citation_text,expected.citation_text,"Verified reference must show its exact expected citation");
  assert.ok(reference.citation_text.includes(expected.locator),"Printed part/page locator is missing");
}

// Executed inside the actual browser document via CDP, not in a DOM substitute.
// PR61 renders each reference as status paragraph, original-pointer pre, citation
// paragraph, before the next h3. Keep source/question text exact; trim labels only.
export function readReferenceDetail(doc,href) {
  const article=doc.querySelector("#wave7-persisted article");
  if(!article)throw Error("Persisted detail article missing");
  const nodes=[...article.children];
  const start=nodes.findIndex(node=>node.tagName==="H3"&&node.textContent.trim()==="الإحالات المحفوظة");
  if(start<0)throw Error("Persisted references section missing");
  const references=[];
  for(let index=start+1;index<nodes.length&&nodes[index].tagName!=="H3";index+=3){
    const [status,pointer,citation]=nodes.slice(index,index+3);
    const match=status?.textContent.trim().match(/^حالة التحقق: (VERIFIED|UNVERIFIED|MISMATCHED) — فهرس اصطناعي فقط$/u);
    if(status?.tagName!=="P"||!match||pointer?.tagName!=="PRE"||citation?.tagName!=="P"){
      throw Error("Malformed or missing persisted reference/status/citation");
    }
    references.push({reference_ordinal:references.length+1,status:match[1],
      original_pointer:pointer.textContent,citation_text:citation.textContent});
  }
  const url=new URL(href);
  return {batch_id:url.searchParams.get("batch"),row_id:url.searchParams.get("row"),
    question:article.querySelector("p.original-text")?.textContent,references};
}
