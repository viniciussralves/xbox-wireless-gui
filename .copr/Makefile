# COPR build helper: `srpm` target packs the current checkout.
# https://docs.pagure.org/copr.copr/user_documentation.html#make-srpm
srpm:
	mkdir -p $(OUTDIR)
	rm -rf /tmp/copr-xwg && mkdir -p /tmp/copr-xwg
	git archive --format=tar.gz --prefix=xbox-wireless-gui-0.1.0/ \
		-o /tmp/copr-xwg/xbox-wireless-gui-0.1.0.tar.gz HEAD
	cp /tmp/copr-xwg/xbox-wireless-gui-0.1.0.tar.gz $(OUTDIR)/
	rpmbuild -bs --define "_sourcedir $(OUTDIR)" \
		--define "_srcrpmdir $(OUTDIR)" fedora/xbox-wireless-gui.spec
