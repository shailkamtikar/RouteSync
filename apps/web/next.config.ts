import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  cacheComponents: true,
  partialPrefetching: true,
  // The dev indicator sits over the corner of the sidebar and gets in the way of clicks.
  devIndicators: false,
};

export default nextConfig;
