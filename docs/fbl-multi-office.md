# FBL shared application locations

Follow-up to the Lachute repair: FBL revision 3 from catalog PR 36, commit d7c9f2f96bafb6265d37003e960e98286183c903. All other 871 pins are unchanged.

The source exposes 42 office cards but only 33 distinct application URLs. Its shared internship URL now retains all ten structured office addresses, including Lachute. The canonical lifecycle unions explicit office evidence within one source snapshot without creating duplicate jobs. A later snapshot can replace removed offices; the regression covers both union and replacement.

Validation: fresh FBL run, all ten addresses retained through the public lifecycle, canonical regression tests, 170 exported feed tests, catalog schema/build/10 tests, and export integrity. The source remains bounded and does not prove company-wide exhaustion.
