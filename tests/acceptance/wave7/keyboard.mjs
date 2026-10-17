// CDP transport helper shared by actual browser interactions and transport regressions.
export async function dispatchKey(cdp, key, virtualKeyCode) {
  for (const type of ["keyDown", "keyUp"]) {
    const params={type,key,windowsVirtualKeyCode:virtualKeyCode};
    if (key === "Enter") {
      params.code="Enter";
      if (type === "keyDown") {
        params.text="\r";
        params.unmodifiedText="\r";
      }
    }
    await cdp.send("Input.dispatchKeyEvent",params);
  }
}
