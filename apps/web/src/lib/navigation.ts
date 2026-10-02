export type NavigationItem = { href: string; label: string };

/** Keep public and account destinations in one mobile menu without duplicates. */
export function mobileNavigation(
  publicItems: readonly NavigationItem[],
  accountItems: readonly NavigationItem[],
  signedIn: boolean,
  login: NavigationItem,
): NavigationItem[] {
  const items = signedIn ? [...publicItems, ...accountItems] : [...publicItems, login];
  const seen = new Set<string>();
  return items.filter(({ href }) => {
    if (seen.has(href)) return false;
    seen.add(href);
    return true;
  });
}
