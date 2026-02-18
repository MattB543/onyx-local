import { DocumentSetSummary } from "../types";
import { fetchSS } from "../utilsSS";
import { Connector } from "../connectors/connectors";

export async function fetchValidFilterInfo() {
  const [connectorsResponse, documentSetResponse] = await Promise.all([
    fetchSS("/manage/connector"),
    fetchSS("/manage/document-set"),
  ]);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let connectors = [] as Connector<any>[];
  if (connectorsResponse.ok) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    connectors = (await connectorsResponse.json()) as Connector<any>[];
  } else {
    console.log(
      `Failed to fetch connectors - ${connectorsResponse.status} - ${connectorsResponse.statusText}`
    );
  }

  let documentSets = [] as DocumentSetSummary[];
  if (documentSetResponse.ok) {
    documentSets = (await documentSetResponse.json()) as DocumentSetSummary[];
  } else {
    console.log(
      `Failed to fetch document sets - ${documentSetResponse.status} - ${documentSetResponse.statusText}`
    );
  }

  return { connectors, documentSets };
}
