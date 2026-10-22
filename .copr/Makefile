# COPR build helper: `srpm` target packs the current checkout.
# https://docs.pagure.org/copr.copr/user_documentation.html#make-srpm
NAME := xbox-wireless-gui
VERSION := $(shell awk '/^Version:/{print $$2; exit}' fedora/$(NAME).spec)
TARBALL := $(NAME)-$(VERSION).tar.gz

srpm:
	mkdir -p $(OUTDIR)
	rm -rf /tmp/copr-xwg && mkdir -p /tmp/copr-xwg
	git archive --format=tar.gz --prefix=$(NAME)-$(VERSION)/ \
		-o /tmp/copr-xwg/$(TARBALL) HEAD
	cp /tmp/copr-xwg/$(TARBALL) $(OUTDIR)/
	rpmbuild -bs --define "_sourcedir $(OUTDIR)" \
		--define "_srcrpmdir $(OUTDIR)" fedora/$(NAME).spec
