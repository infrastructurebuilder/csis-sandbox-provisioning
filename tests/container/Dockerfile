# A stand-in for a freshly booted head node: AlmaLinux 10 with systemd as its
# first process, the login user that the AWS image has, and the two tools the
# first-boot template installs before it runs the playbook.
FROM almalinux:10

RUN dnf -y install systemd sudo openssh-clients tar git ansible-core \
    && dnf clean all

RUN useradd --create-home --groups wheel ec2-user \
    && echo 'ec2-user ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/90-ec2-user \
    && chmod 0440 /etc/sudoers.d/90-ec2-user

CMD ["/usr/sbin/init"]
