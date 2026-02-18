import { AdminPageTitle } from "@/components/admin/Title";
import { fetchValidFilterInfo } from "@/lib/search/utilsSS";

import { SvgZoomIn } from "@opal/icons";

import { Explorer } from "./Explorer";
export default async function Page(props: {
  searchParams: Promise<Record<string, string>>;
}) {
  const searchParams = await props.searchParams;
  const { connectors, documentSets } = await fetchValidFilterInfo();

  return (
    <>
      <AdminPageTitle
        icon={<SvgZoomIn className="stroke-text-04 h-8 w-8" />}
        title="Document Explorer"
      />

      <Explorer
        initialSearchValue={searchParams.query}
        connectors={connectors}
        documentSets={documentSets}
      />
    </>
  );
}
