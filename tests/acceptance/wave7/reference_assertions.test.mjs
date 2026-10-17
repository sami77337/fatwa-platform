import {test} from "node:test";
import assert from "node:assert/strict";
import {assertVerifiedReference} from "./reference_assertions.mjs";

const citation="إحالة إلى عنوان في فهرس مرجع اصطناعي لتجارب Wave7: كِتَابٌ اصطناعي / بابٌ اصطناعي أول، ج الأول، ص 8 (عنوان فهرس، وليس نص فتوى).";
const expected={batch_id:"e6-batch-a",row_id:"e6-row-7",question:"  سُؤَالٌ\tأصلي\n  ",
  reference_ordinal:1,original_pointer:'{"source_id":"W7-SOURCE","heading_id":"W7-HEADING-2"}',
  citation_text:citation,locator:"، ج الأول، ص 8 "};
function snapshot(){return {batch_id:expected.batch_id,row_id:expected.row_id,question:expected.question,
  references:[{reference_ordinal:1,status:"VERIFIED",original_pointer:expected.original_pointer,citation_text:citation}]};}

test("verified reference passes only with exact row/source/citation/printed locator",()=>{
  assert.doesNotThrow(()=>assertVerifiedReference(snapshot(),expected));
});
test("UNVERIFIED never passes even when it contains the VERIFIED substring or exact citation",()=>{
  for(const text of ["",citation]){
    const actual=snapshot();Object.assign(actual.references[0],{status:"UNVERIFIED",citation_text:text});
    assert.throws(()=>assertVerifiedReference(actual,expected));
  }
});
test("MISMATCHED with no citation is rejected",()=>{
  const actual=snapshot();Object.assign(actual.references[0],{status:"MISMATCHED",citation_text:""});
  assert.throws(()=>assertVerifiedReference(actual,expected));
});
test("VERIFIED without citation is rejected",()=>{
  const actual=snapshot();actual.references[0].citation_text="";
  assert.throws(()=>assertVerifiedReference(actual,expected));
});
test("VERIFIED with unrelated citation content is rejected",()=>{
  const actual=snapshot();actual.references[0].citation_text=citation.replace("بابٌ اصطناعي أول","باب آخر");
  assert.throws(()=>assertVerifiedReference(actual,expected));
});
test("VERIFIED with the wrong printed locator is rejected",()=>{
  const actual=snapshot();actual.references[0].citation_text=citation.replace("ص 8 ","ص 9 ");
  assert.throws(()=>assertVerifiedReference(actual,expected));
});
test("a verified citation on another row is rejected",()=>{
  const actual=snapshot();actual.row_id="e6-other-row";
  assert.throws(()=>assertVerifiedReference(actual,expected));
});
test("same external question/citation in another batch cannot satisfy identity",()=>{
  const actual=snapshot();actual.batch_id="e6-batch-b";
  assert.throws(()=>assertVerifiedReference(actual,expected));
});
test("a verified citation beside the wrong original pointer is rejected",()=>{
  const actual=snapshot();actual.references[0].original_pointer='{"source_id":"W7-SOURCE","heading_id":"W7-HEADING-1"}';
  assert.throws(()=>assertVerifiedReference(actual,expected));
});
test("missing reference cannot be satisfied by VERIFIED text elsewhere",()=>{
  const actual=snapshot();actual.references=[];actual.body_text="VERIFIED "+citation;
  assert.throws(()=>assertVerifiedReference(actual,expected));
});
