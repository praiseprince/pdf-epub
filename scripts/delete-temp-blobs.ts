import { del, list } from "@vercel/blob";
import { isValidJobBlobPath } from "../src/lib/blob/paths";

async function main() {
  let cursor: string | undefined;
  let deleted = 0;

  do {
    const page = await list({
      prefix: "tmp/",
      limit: 1000,
      ...(cursor ? { cursor } : {})
    });
    const pathnames = page.blobs.map((blob) => blob.pathname).filter(isValidJobBlobPath);

    if (pathnames.length > 0) {
      await del(pathnames);
      deleted += pathnames.length;
    }

    cursor = page.cursor;
    if (!page.hasMore) {
      break;
    }
  } while (cursor);

  console.log(`Deleted ${deleted} temporary Blob object(s).`);
}

main().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : "Failed to delete temporary Blob objects.");
  process.exitCode = 1;
});
