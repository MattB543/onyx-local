import { Route } from "next";
import Link from "next/link";

import Text from "@/refresh-components/texts/Text";

import { SvgChevronRight } from "@opal/icons";

interface BreadcrumbItem {
  label: string;
  href?: string;
}

interface CrmBreadcrumbsProps {
  items: BreadcrumbItem[];
}

export default function CrmBreadcrumbs({ items }: CrmBreadcrumbsProps) {
  return (
    <nav className="flex items-center gap-1" aria-label="Breadcrumb">
      {items.map((item, index) => {
        const isLast = index === items.length - 1;
        return (
          <span key={index} className="flex items-center gap-1">
            {index > 0 && (
              <SvgChevronRight size={14} className="shrink-0 stroke-text-03" />
            )}
            {item.href && !isLast ? (
              <Link href={item.href as Route} className="hover:underline">
                <Text as="span" secondaryBody text03 className="text-sm">
                  {item.label}
                </Text>
              </Link>
            ) : (
              <Text
                as="span"
                secondaryBody
                text02
                className="text-sm font-medium"
              >
                {item.label}
              </Text>
            )}
          </span>
        );
      })}
    </nav>
  );
}
